"""flight-ecpay-period: ECPay PeriodReturnURL (2nd charge onward of a 信用卡定期定額 order).

Success keeps the row active and extends current_period_end by one period. A failed renewal does
NOT expire the row: ECPay retries and only terminates after 6 consecutive failures, so we count
failures and expire at 6. Verifies CheckMacValue, ignores SimulatePaid, answers plain-text 1|OK.
"""
import base64, calendar, hashlib, hmac, json, urllib.parse
from datetime import datetime, timedelta, timezone
import boto3
from boto3.dynamodb.conditions import Attr

TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
TZ_TPE = timezone(timedelta(hours=8))
MAX_FAILED = 6

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
    months = 12 * frequency if period_type == "Y" else frequency
    y, m = divmod(start.month - 1 + months, 12)
    y, m = start.year + y, m + 1
    return start.replace(year=y, month=m, day=min(start.day, calendar.monthrange(y, m)[1]))


def _find_row(email, route, trade_no):
    if email and route:
        row = _table.get_item(Key={"email": email, "route": route}).get("Item")
        if row:
            return row
    kwargs = {"FilterExpression": Attr("merchant_trade_no").eq(trade_no)}
    while True:
        page = _table.scan(**kwargs)
        if page.get("Items"):
            return page["Items"][0]
        if "LastEvaluatedKey" not in page:
            return None
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def handler(event, context):
    p = _form(event)
    cfg = _ecpay()
    if not verify_cmv(p, cfg["hash_key"], cfg["hash_iv"]):
        print("CheckMacValue mismatch:", {k: v for k, v in p.items() if k != "CheckMacValue"})
        return _text("0|CheckMacValueInvalid", 400)
    if p.get("MerchantID") != str(cfg["merchant_id"]):
        return _text("0|MerchantIDMismatch", 400)

    trade_no = p.get("MerchantTradeNo", "")
    print(f"PeriodReturnURL trade={trade_no} rtn={p.get('RtnCode')} msg={p.get('RtnMsg')} "
          f"success_times={p.get('TotalSuccessTimes')} simulate={p.get('SimulatePaid')}")
    if p.get("SimulatePaid") == "1":
        print("SimulatePaid=1: verified and acknowledged, NOT changing the subscription")
        return _text("1|OK")

    row = _find_row(p.get("CustomField1", "").strip().lower(), p.get("CustomField2", "").strip(), trade_no)
    if not row:
        print("no subscription row for trade", trade_no)
        return _text("1|OK")
    if row.get("merchant_trade_no") != trade_no:
        print(f"callback for an older order {trade_no}; row now uses {row.get('merchant_trade_no')} - ignoring")
        return _text("1|OK")
    key = {"email": row["email"], "route": row["route"]}
    now = datetime.now(timezone.utc)

    if p.get("RtnCode") == "1":
        if row.get("subscription_status") not in ("active", "cancelled"):
            print("renewal for a row in status", row.get("subscription_status"), "- leaving status unchanged")
        base = now
        try:
            current = datetime.strptime(row.get("current_period_end", ""), TS_FMT).replace(tzinfo=timezone.utc)
            base = max(current, now)
        except ValueError:
            pass
        end = add_period(base, p.get("PeriodType") or row.get("period_type", "M"), int(p.get("Frequency") or row.get("frequency", 1)))
        _table.update_item(
            Key=key,
            UpdateExpression=("SET current_period_end=:e, current_period_end_date=:d, last_charged_at=:n, "
                              "failed_renewals=:z, total_success_times=:s, updated_at=:n"),
            ExpressionAttributeValues={":e": end.strftime(TS_FMT), ":d": end.astimezone(TZ_TPE).strftime("%Y-%m-%d"),
                                       ":n": now.strftime(TS_FMT), ":z": 0, ":s": int(p.get("TotalSuccessTimes") or 0)},
        )
        print(f"renewed {key['email']}#{key['route']} until {end.strftime(TS_FMT)}")
        return _text("1|OK")

    failed = int(row.get("failed_renewals", 0)) + 1
    updates, values = "SET failed_renewals=:f, last_failed_at=:n, updated_at=:n", {":f": failed, ":n": now.strftime(TS_FMT)}
    if failed >= MAX_FAILED:
        updates += ", subscription_status=:x"
        values[":x"] = "expired"
    _table.update_item(Key=key, UpdateExpression=updates, ExpressionAttributeValues=values)
    print(f"renewal failed ({failed}/{MAX_FAILED}) for {key['email']}#{key['route']}"
          + (" - ECPay terminates the series, row expired" if failed >= MAX_FAILED else " - ECPay will retry"))
    return _text("1|OK")
