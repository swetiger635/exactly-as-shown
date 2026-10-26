"""flight-ecpay-return: ECPay ReturnURL (first charge of a 信用卡定期定額 order).

The ONLY place a row becomes `active` on first payment. Verifies CheckMacValue (keeping empty
fields) + MerchantID, ignores SimulatePaid, is idempotent on MerchantTradeNo, sets
current_period_end, enqueues a "welcome" status event, and always answers plain-text 1|OK.
"""
import base64, calendar, hashlib, hmac, json, os, urllib.parse
from datetime import datetime, timedelta, timezone
import boto3

TS_FMT = "%Y-%m-%dT%H:%M:%SZ"  # fixed-width UTC: grace checks compare these as strings
TZ_TPE = timezone(timedelta(hours=8))

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


def _ecpay():
    if "ecpay" not in _cache:
        _cache["ecpay"] = json.loads(_secrets.get_secret_value(SecretId="flight/ecpay")["SecretString"])
    return _cache["ecpay"]


def _text(body, status=200):
    return {"statusCode": status, "headers": {"Content-Type": "text/plain; charset=utf-8"}, "body": body}


def _form(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}


def add_period(start, period_type, frequency=1):
    if period_type == "D":
        return start + timedelta(days=frequency)
    if period_type == "Y":
        months = 12 * frequency
    else:
        months = frequency
    y, m = divmod(start.month - 1 + months, 12)
    y, m = start.year + y, m + 1
    return start.replace(year=y, month=m, day=min(start.day, calendar.monthrange(y, m)[1]))


def _status_queue():
    if "q" not in _cache:
        _cache["q"] = _sqs.get_queue_url(QueueName=os.environ.get("STATUS_QUEUE", "flight-status-queue"))["QueueUrl"]
    return _cache["q"]


def handler(event, context):
    p = _form(event)
    cfg = _ecpay()
    if not verify_cmv(p, cfg["hash_key"], cfg["hash_iv"]):
        print("CheckMacValue mismatch:", {k: v for k, v in p.items() if k != "CheckMacValue"})
        return _text("0|CheckMacValueInvalid", 400)
    if p.get("MerchantID") != str(cfg["merchant_id"]):
        print("MerchantID mismatch:", p.get("MerchantID"))
        return _text("0|MerchantIDMismatch", 400)

    trade_no = p.get("MerchantTradeNo", "")
    email, route = p.get("CustomField1", "").strip().lower(), p.get("CustomField2", "").strip()
    print(f"ReturnURL trade={trade_no} rtn={p.get('RtnCode')} msg={p.get('RtnMsg')} simulate={p.get('SimulatePaid')} "
          f"email={email} route={route}")

    if p.get("SimulatePaid") == "1":
        print("SimulatePaid=1: verified and acknowledged, NOT activating")
        return _text("1|OK")
    if p.get("RtnCode") != "1":
        print("first authorization failed - row stays pending_payment (ECPay will not schedule renewals)")
        return _text("1|OK")
    if not email or not route:
        print("missing CustomField1/2 - cannot locate the subscription row")
        return _text("1|OK")

    row = _table.get_item(Key={"email": email, "route": route}).get("Item")
    if not row:
        print("no subscription row for", email, route)
        return _text("1|OK")
    if row.get("subscription_status") == "active" and row.get("merchant_trade_no") == trade_no:
        print("already active for this MerchantTradeNo - idempotent no-op")
        return _text("1|OK")

    now = datetime.now(timezone.utc)
    period_type = p.get("PeriodType") or "M"
    frequency = int(p.get("Frequency") or 1)
    end = add_period(now, period_type, frequency)
    _table.update_item(
        Key={"email": email, "route": route},
        UpdateExpression=("SET subscription_status=:a, merchant_trade_no=:t, current_period_end=:e, "
                          "current_period_end_date=:d, activated_at=:n, last_charged_at=:n, period_type=:pt, "
                          "frequency=:f, failed_renewals=:z, updated_at=:n"),
        ExpressionAttributeValues={":a": "active", ":t": trade_no, ":e": end.strftime(TS_FMT),
                                   ":d": end.astimezone(TZ_TPE).strftime("%Y-%m-%d"), ":n": now.strftime(TS_FMT),
                                   ":pt": period_type, ":f": frequency, ":z": 0},
    )
    _sqs.send_message(QueueUrl=_status_queue(), MessageBody=json.dumps({
        "event_type": "welcome", "email": email, "route": route, "merchant_trade_no": trade_no,
        "target_price": int(row.get("target_price", 0)), "amount": p.get("PeriodAmount") or p.get("TradeAmt") or cfg.get("amount"),
        "current_period_end_date": end.astimezone(TZ_TPE).strftime("%Y-%m-%d")}))
    print(f"activated {email}#{route} until {end.strftime(TS_FMT)}")
    return _text("1|OK")
