"""flight-cancel-subscription (M2): POST /cancel for the signed-in user.

Calls ECPay CreditCardPeriodAction Action=Cancel to stop future charges, then sets the row to
`cancelled` (NOT expired): the user keeps alerts until current_period_end, when the parser expires it.
"""
import base64, calendar, hashlib, hmac, json, os, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
import boto3

TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
TZ_TPE = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (compatible; flight-notifier/1.0)"
PERIOD_ACTION = {"stage": "https://payment-stage.ecpay.com.tw/Cashier/CreditCardPeriodAction",
                 "prod": "https://payment.ecpay.com.tw/Cashier/CreditCardPeriodAction"}

_secrets = boto3.client("secretsmanager")
_sqs = boto3.client("sqs")
_table = boto3.resource("dynamodb").Table("subscriptions")
_cache = {}


# --- ECPay CheckMacValue ---
def ecpay_url_encode(s):
    e = urllib.parse.quote_plus(str(s)).replace("~", "%7E")
    e = e.lower()
    for o, n in (("%2d", "-"), ("%5f", "_"), ("%2e", "."), ("%21", "!"), ("%2a", "*"), ("%28", "("), ("%29", ")")):
        e = e.replace(o, n)
    return e


def gen_cmv(params, hash_key, hash_iv, method="SHA256"):
    items = {k: v for k, v in params.items() if k != "CheckMacValue"}  # KEEP empty-string values
    body = "&".join(f"{k}={items[k]}" for k in sorted(items, key=str.lower))
    raw = ecpay_url_encode(f"HashKey={hash_key}&{body}&HashIV={hash_iv}").encode()
    return (hashlib.md5(raw) if method.upper() == "MD5" else hashlib.sha256(raw)).hexdigest().upper()


def verify_cmv(params, hash_key, hash_iv):
    got = params.get("CheckMacValue", "")
    return bool(got) and hmac.compare_digest(got.upper(), gen_cmv(params, hash_key, hash_iv))
# --- end CheckMacValue ---


def _secret(name):
    if name not in _cache:
        _cache[name] = json.loads(_secrets.get_secret_value(SecretId=name)["SecretString"])
    return _cache[name]


# --- Supabase auth ---
def caller_email(event, fallback=None):
    """Email of the signed-in Supabase user (Authorization: Bearer <access token>).
    Direct Lambda invokes carry no API Gateway requestContext and need IAM, so they may pass the email."""
    if "requestContext" not in event:
        return (fallback or "").strip().lower() or None
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    sb = _secret("flight/supabase")
    key = sb.get("publishable_key") or sb.get("anon_key") or sb.get("key")
    req = urllib.request.Request(sb["url"].rstrip("/") + "/auth/v1/user",
                                 headers={"apikey": key, "Authorization": auth, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            user = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print("auth check failed:", e)
        return None
    return (user.get("email") or "").strip().lower() or None
# --- end Supabase auth ---


def _json(code, body):
    return {"statusCode": code, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def add_month(start):
    y, m = divmod(start.month, 12)
    y, m = start.year + y, m + 1
    return start.replace(year=y, month=m, day=min(start.day, calendar.monthrange(y, m)[1]))


def ecpay_cancel(cfg, trade_no):
    params = {"MerchantID": str(cfg["merchant_id"]), "MerchantTradeNo": trade_no, "Action": "Cancel",
              "TimeStamp": str(int(time.time()))}
    params["CheckMacValue"] = gen_cmv(params, cfg["hash_key"], cfg["hash_iv"])
    req = urllib.request.Request(PERIOD_ACTION.get(cfg.get("env", "stage"), PERIOD_ACTION["stage"]),
                                 data=urllib.parse.urlencode(params).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as e:
        return {"RtnCode": "", "RtnMsg": f"request failed: {e}"}
    res = {k: v[0] for k, v in urllib.parse.parse_qs(body, keep_blank_values=True).items()}
    return res or {"RtnCode": "", "RtnMsg": body[:200]}


def handler(event, context):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        data = json.loads(raw)
    except ValueError:
        return _json(400, {"error": "invalid JSON"})
    email = caller_email(event, data.get("email"))
    if not email:
        return _json(401, {"error": "sign in required"})
    route = str(data.get("route", "")).strip()
    row = _table.get_item(Key={"email": email, "route": route}).get("Item")
    if not row:
        return _json(404, {"error": "subscription not found"})
    status = row.get("subscription_status")
    if status == "cancelled":
        return _json(200, {"ok": True, "subscription_status": "cancelled",
                           "current_period_end_date": row.get("current_period_end_date")})
    if status != "active":
        return _json(409, {"error": f"only an active subscription can be cancelled (status: {status or 'pending_payment'})"})

    trade_no = row.get("merchant_trade_no", "")
    res = ecpay_cancel(_secret("flight/ecpay"), trade_no)
    print(f"ECPay Cancel {trade_no}: RtnCode={res.get('RtnCode')} RtnMsg={res.get('RtnMsg')}")

    now = datetime.now(timezone.utc)
    end_s, end_d = row.get("current_period_end"), row.get("current_period_end_date")
    if not end_s:  # activated before period tracking existed: give one month of grace
        end = add_month(now)
        end_s, end_d = end.strftime(TS_FMT), end.astimezone(TZ_TPE).strftime("%Y-%m-%d")
    _table.update_item(
        Key={"email": email, "route": route},
        UpdateExpression=("SET subscription_status=:c, current_period_end=:e, current_period_end_date=:d, "
                          "cancelled_at=:n, ecpay_cancel_result=:r, updated_at=:n"),
        ExpressionAttributeValues={":c": "cancelled", ":e": end_s, ":d": end_d, ":n": now.strftime(TS_FMT),
                                   ":r": f"{res.get('RtnCode')}|{res.get('RtnMsg')}"},
    )
    qurl = _sqs.get_queue_url(QueueName=os.environ.get("STATUS_QUEUE", "flight-status-queue"))["QueueUrl"]
    _sqs.send_message(QueueUrl=qurl, MessageBody=json.dumps({
        "event_type": "cancel", "email": email, "route": route, "merchant_trade_no": trade_no,
        "current_period_end_date": end_d}))
    return _json(200, {"ok": True, "subscription_status": "cancelled", "current_period_end_date": end_d,
                       "ecpay": {"RtnCode": res.get("RtnCode"), "RtnMsg": res.get("RtnMsg")}})
