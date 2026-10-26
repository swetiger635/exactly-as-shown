"""flight-list-subscriptions (M2): GET /subscriptions for the signed-in user, plus the monthly price."""
import json, urllib.error, urllib.request
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Key

UA = "Mozilla/5.0 (compatible; flight-notifier/1.0)"
_secrets = boto3.client("secretsmanager")
ddb = boto3.resource("dynamodb").Table("subscriptions")
_cache = {}
PUBLIC = ("email", "route", "plan_name", "origin", "destination", "target_price", "currency", "subscription_status",
          "current_period_end", "current_period_end_date", "created_at", "updated_at")


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


def _plain(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def handler(event, context):
    email = caller_email(event, (event.get("queryStringParameters") or {}).get("email"))
    if not email:
        return {"statusCode": 401, "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "sign in required"})}
    items = ddb.query(KeyConditionExpression=Key("email").eq(email)).get("Items", [])
    rows = [{k: _plain(it[k]) for k in PUBLIC if k in it} for it in items]
    for r in rows:
        r.setdefault("subscription_status", "pending_payment")  # legacy M1 rows were never paid
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"subscriptions": rows, "monthly_price": int(_secret("flight/ecpay").get("amount", 0))})}
