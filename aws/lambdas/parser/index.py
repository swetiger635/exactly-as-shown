"""flight-parser: one route per invocation.

Fetch next month's cheapest fare (TWD = the gate, USD = best-effort extra line),
scan subscribers on that route, and enqueue every PAYING subscriber whose TWD target is met.

M2 paywall (grace-aware): serve `active` rows and `cancelled` rows still inside their paid period
(current_period_end >= now). A cancelled row whose period has passed is lazily flipped to `expired`.
pending_payment / expired / legacy rows without a status are never alerted.
"""
import json, os, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Attr

UA = "Mozilla/5.0 (compatible; flight-notifier/1.0)"
TS_FMT = "%Y-%m-%dT%H:%M:%SZ"  # must match the callbacks: grace checks compare these strings
TZ_TPE = timezone(timedelta(hours=8))

_secrets = boto3.client("secretsmanager")
_sqs = boto3.client("sqs")
_table = boto3.resource("dynamodb").Table("subscriptions")
_token = None
_qurl = None


def _get_token():
    global _token
    if _token is None:
        raw = _secrets.get_secret_value(SecretId="flight/travelpayouts")["SecretString"]
        try:
            _token = json.loads(raw)["token"]
        except (ValueError, KeyError, TypeError):
            _token = raw.strip()
    return _token


def _queue_url():
    global _qurl
    if _qurl is None:
        _qurl = _sqs.get_queue_url(QueueName=os.environ.get("FARE_QUEUE", "flight-fare-queue"))["QueueUrl"]
    return _qurl


def next_month():
    now = datetime.now(TZ_TPE)
    y, m = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return f"{y:04d}-{m:02d}"


def fetch_cheapest(origin, destination, month, token, currency):
    q = urllib.parse.urlencode({"origin": origin, "destination": destination, "depart_date": month,
                                "currency": currency, "token": token})
    req = urllib.request.Request(f"https://api.travelpayouts.com/v1/prices/cheap?{q}",
                                 headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"travelpayouts {currency} HTTP {e.code} for {origin}-{destination}")
        return None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"travelpayouts {currency} error for {origin}-{destination}: {e}")
        return None
    if not body.get("success") or not body.get("data"):
        return None
    offers = body["data"].get(destination, {})
    if not offers:
        return None
    best = min(offers.values(), key=lambda o: o["price"])
    return {"price": best["price"], "currency": currency.upper(), "airline": best.get("airline"),
            "depart_date": best.get("departure_at"), "return_date": best.get("return_at")}


def _subscribers(route):
    kwargs = {"FilterExpression": Attr("route").eq(route)}
    while True:
        page = _table.scan(**kwargs)
        yield from page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def paid_status(item, now_s):
    """'serve', 'expire' (cancelled and past its paid period) or 'skip'."""
    status = item.get("subscription_status")
    if status == "active":
        return "serve"
    if status == "cancelled":
        return "serve" if item.get("current_period_end", "") >= now_s else "expire"
    return "skip"


def handler(event, context):
    origin = event["origin"]
    destination = event["destination"]
    route = event.get("route") or f"{origin}-{destination}"
    month = event.get("month") or next_month()
    token = _get_token()

    tw = fetch_cheapest(origin, destination, month, token, "twd")
    if not tw:
        print(f"no TWD fare for {route} {month} (empty/429) - skipping")
        return {"ok": True, "route": route, "matched": 0}
    us = fetch_cheapest(origin, destination, month, token, "usd")  # optional, never blocks
    print(f"{route} {month} cheapest {tw['price']} TWD ({tw['airline']})"
          + (f" / {us['price']} USD" if us else " / USD n/a"))

    cheapest = Decimal(str(tw["price"]))
    now_s = datetime.now(timezone.utc).strftime(TS_FMT)
    matched, unpaid, expired = 0, 0, 0
    for it in _subscribers(route):
        decision = paid_status(it, now_s)
        if decision == "expire":
            _table.update_item(Key={"email": it["email"], "route": it["route"]},
                               UpdateExpression="SET subscription_status=:x, expired_at=:n, updated_at=:n",
                               ConditionExpression="subscription_status = :c",
                               ExpressionAttributeValues={":x": "expired", ":c": "cancelled", ":n": now_s})
            expired += 1
            continue
        if decision == "skip":
            unpaid += 1
            continue
        tp = it.get("target_price")
        if tp is None or Decimal(str(tp)) < cheapest:
            continue
        body = {"email": it["email"], "route": route, "plan_name": it.get("plan_name"),
                "target_price": int(tp),
                "cheapest": {"price": tw["price"], "currency": "TWD", "airline": tw["airline"],
                             "depart_date": tw["depart_date"], "return_date": tw["return_date"]}}
        if us:
            body["cheapest_usd"] = {"price": us["price"], "currency": "USD", "airline": us["airline"],
                                    "depart_date": us["depart_date"], "return_date": us["return_date"]}
        _sqs.send_message(QueueUrl=_queue_url(), MessageBody=json.dumps(body))
        matched += 1
    print(f"{route}: enqueued {matched} match(es); skipped {unpaid} unpaid; expired {expired} after grace")
    return {"ok": True, "route": route, "month": month, "cheapest_twd": tw["price"], "matched": matched,
            "skipped_unpaid": unpaid, "expired_after_grace": expired}
