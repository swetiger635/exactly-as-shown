"""flight-save-subscription (M2): POST /subscribe.

The subscriber is the signed-in Supabase user (never a client-supplied email).
- Paid rows (active, or cancelled but still inside the paid period): update the target in place, JSON.
- Everything else (new, pending_payment, expired, legacy M1 rows): write pending_payment + a fresh
  MerchantTradeNo and return an auto-submit HTML form that posts the browser to ECPay's 信用卡定期定額
  cashier. Only the ReturnURL callback can make a row active.
"""
import base64, hashlib, hmac, html, json, os, re, secrets, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import boto3

PLANS = {"tokyo": ("TPE", "TYO", "東京"), "seoul": ("TPE", "SEL", "首爾"), "london": ("TPE", "LON", "倫敦")}
TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
TZ_TPE = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (compatible; flight-notifier/1.0)"
CASHIER = {"stage": "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5",
           "prod": "https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5"}

_secrets = boto3.client("secretsmanager")
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


def _in_grace(row, now_s):
    return row.get("subscription_status") == "cancelled" and row.get("current_period_end", "") >= now_s


def checkout_form(cfg, trade_no, email, route, title):
    api = os.environ["API_BASE"].strip().rstrip("/")
    amount = str(int(cfg["amount"]))
    params = {
        "MerchantID": str(cfg["merchant_id"]), "MerchantTradeNo": trade_no,
        "MerchantTradeDate": datetime.now(TZ_TPE).strftime("%Y/%m/%d %H:%M:%S"),
        "PaymentType": "aio", "TotalAmount": amount, "TradeDesc": "Flight Price Notifier monthly plan",
        "ItemName": f"Flight Price Notifier 月訂閱 台北-{title}", "ChoosePayment": "Credit", "EncryptType": "1",
        "ReturnURL": f"{api}/ecpay-return", "OrderResultURL": f"{api}/ecpay-result",
        "PeriodAmount": amount, "PeriodType": os.environ.get("PERIOD_TYPE", "M").strip(),
        "Frequency": os.environ.get("FREQUENCY", "1").strip(), "ExecTimes": os.environ.get("EXEC_TIMES", "999").strip(),
        "PeriodReturnURL": f"{api}/ecpay-period", "CustomField1": email, "CustomField2": route,
    }
    params["CheckMacValue"] = gen_cmv(params, cfg["hash_key"], cfg["hash_iv"])
    inputs = "\n".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in params.items())
    action = CASHIER.get(cfg.get("env", "stage"), CASHIER["stage"])
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>前往綠界付款</title></head>'
            f'<body><p style="font-family:sans-serif">正在前往綠界付款頁面…</p>'
            f'<form method="post" action="{action}">{inputs}</form>'
            f'<script>document.forms[0].submit()</script></body></html>')


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
    plan = str(data.get("plan_name", "")).strip().lower()
    if plan not in PLANS:
        return _json(400, {"error": "plan_name must be one of: " + ", ".join(PLANS)})
    try:
        target = Decimal(str(data.get("target_price")))
    except Exception:
        return _json(400, {"error": "target_price must be a number"})
    if not target.is_finite() or target <= 0 or target > 1000000:
        return _json(400, {"error": "target_price must be a positive TWD amount"})
    target = target.quantize(Decimal("1"))

    origin, dest, title = PLANS[plan]
    route = f"{origin}-{dest}"
    key = {"email": email, "route": route}
    now = datetime.now(timezone.utc).strftime(TS_FMT)
    row = _table.get_item(Key=key).get("Item") or {}

    if row.get("subscription_status") == "active" or _in_grace(row, now):
        _table.update_item(Key=key, UpdateExpression="SET target_price=:t, updated_at=:n",
                           ExpressionAttributeValues={":t": target, ":n": now})
        return _json(200, {"ok": True, "mode": "updated", "route": route, "target_price": int(target),
                           "subscription_status": row.get("subscription_status")})

    trade_no = ("FPN" + datetime.now(TZ_TPE).strftime("%y%m%d%H%M%S") + secrets.token_hex(3).upper())[:20]
    _table.update_item(
        Key=key,
        UpdateExpression=("SET plan_name=:p, origin=:o, destination=:d, target_price=:t, currency=:c, "
                          "subscription_status=:s, merchant_trade_no=:m, updated_at=:n, created_at=if_not_exists(created_at, :n)"),
        ExpressionAttributeValues={":p": plan, ":o": origin, ":d": dest, ":t": target, ":c": "TWD",
                                   ":s": "pending_payment", ":m": trade_no, ":n": now},
    )
    print(f"checkout {email}#{route} trade={trade_no} target={target}")
    return {"statusCode": 200, "headers": {"Content-Type": "text/html; charset=utf-8"},
            "body": checkout_form(_secret("flight/ecpay"), trade_no, email, route, title)}
