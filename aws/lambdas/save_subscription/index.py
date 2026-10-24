import base64, json, re
from datetime import datetime, timezone
from decimal import Decimal
import boto3

PLANS = {"tokyo": ("TPE", "TYO"), "seoul": ("TPE", "SEL"), "london": ("TPE", "LON")}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ddb = boto3.resource("dynamodb").Table("subscriptions")


def _resp(code, body):
    return {"statusCode": code, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def handler(event, context):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        data = json.loads(raw)
    except ValueError:
        return _resp(400, {"error": "invalid JSON"})

    email = str(data.get("email", "")).strip().lower()
    plan = str(data.get("plan_name", "")).strip().lower()
    if not EMAIL_RE.match(email):
        return _resp(400, {"error": "invalid email"})
    if plan not in PLANS:
        return _resp(400, {"error": "plan_name must be tokyo, seoul or london"})
    try:
        target = Decimal(str(data.get("target_price")))
    except Exception:
        return _resp(400, {"error": "target_price must be a number"})
    if not target.is_finite() or target <= 0 or target > 1000000:
        return _resp(400, {"error": "target_price must be a positive TWD amount"})
    target = target.quantize(Decimal("1"))

    origin, dest = PLANS[plan]
    route = f"{origin}-{dest}"
    now = datetime.now(timezone.utc).isoformat()
    ddb.update_item(
        Key={"email": email, "route": route},
        UpdateExpression=(
            "SET plan_name=:p, origin=:o, destination=:d, target_price=:t, currency=:c, "
            "updated_at=:n, created_at=if_not_exists(created_at, :n)"
        ),
        ExpressionAttributeValues={
            ":p": plan, ":o": origin, ":d": dest, ":t": target, ":c": "TWD", ":n": now,
        },
    )
    return _resp(200, {"ok": True, "email": email, "route": route, "plan_name": plan,
                       "target_price": int(target), "currency": "TWD"})
