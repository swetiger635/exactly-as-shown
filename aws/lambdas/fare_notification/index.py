"""flight-fare-notification: SQS consumer.

Per queued match: dedup against notification_history (24h floor, re-alert on a big drop),
render a simple transactional email (NT$ headline + optional ~US$ line + booking button),
send it through Resend, and record history ONLY after a 2xx.
Transient Resend failures (429/5xx) are retried via SQS; permanent ones (4xx) are dropped.
"""
import html, json, os, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Key

UA = "Mozilla/5.0 (compatible; flight-notifier/1.0)"
FLOOR_HOURS = float(os.environ.get("NOTIFY_FLOOR_HOURS", "24"))
REALERT_PCT = float(os.environ.get("REALERT_PCT", "20"))
REALERT_ABS = float(os.environ.get("REALERT_ABS_TWD", "2000"))
CITY = {"TPE": "台北", "TYO": "東京", "SEL": "首爾", "LON": "倫敦"}

_secrets = boto3.client("secretsmanager")
_history = boto3.resource("dynamodb").Table("notification_history")
_cfg = {}


class Transient(Exception):
    pass


def _secret(name):
    if name not in _cfg:
        raw = _secrets.get_secret_value(SecretId=name)["SecretString"]
        try:
            _cfg[name] = json.loads(raw)
        except ValueError:
            _cfg[name] = {"value": raw}
    return _cfg[name]


def _marker():
    try:
        return _secret("flight/travelpayouts").get("marker")
    except Exception:
        return None


# ---------- rendering ----------
def _route_parts(route):
    o, d = route.split("-", 1)
    return o, d


def _twd(n):
    return f"NT${int(n):,}"


def _ddmm(iso):
    return f"{iso[8:10]}{iso[5:7]}" if iso and len(iso) >= 10 else ""


def _day(iso):
    return f"{int(iso[5:7])}/{int(iso[8:10])}" if iso and len(iso) >= 10 else "—"


def booking_url(route, fare, marker=None):
    o, d = _route_parts(route)
    path = f"{o}{_ddmm(fare.get('depart_date'))}{d}{_ddmm(fare.get('return_date'))}1"
    url = f"https://www.aviasales.com/search/{path}?currency=twd"
    return url + (f"&marker={marker}" if marker else "")


def subject(route, fare):
    o, d = _route_parts(route)
    return f"✈️ {CITY.get(o, o)} → {CITY.get(d, d)} 降價通知！{_twd(fare['price'])} 已達標"


def render_text(route, fare, target, usd_price=None, marker=None):
    o, d = _route_parts(route)
    lines = [
        f"{CITY.get(o, o)} → {CITY.get(d, d)} 的最低票價已降到 {_twd(fare['price'])}",
        f"（你的目標價：{_twd(target)}）",
    ]
    if usd_price:
        lines.append(f"約 US${int(usd_price):,}")
    lines += [
        f"航空公司：{fare.get('airline') or '—'}",
        f"去程 {_day(fare.get('depart_date'))}　回程 {_day(fare.get('return_date'))}",
        "",
        f"立即訂購：{booking_url(route, fare, marker)}",
        "",
        "票價隨時變動，以訂購頁面顯示為準。",
        "— Flight Price Notifier",
    ]
    return "\n".join(lines)


def render_html(route, fare, target, usd_price=None, marker=None):
    o, d = _route_parts(route)
    e = html.escape
    usd = (f'<p style="margin:4px 0 0;color:#5b6b78;font-size:14px">約 US${int(usd_price):,}</p>'
           if usd_price else "")
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#faf6ee;font-family:Arial,Helvetica,sans-serif;color:#23394a">
<div style="max-width:480px;margin:0 auto;background:#ffffff;border:1px solid #eadfcb;border-radius:12px;padding:28px">
<p style="margin:0;color:#2f6f73;font-size:14px">{e(CITY.get(o, o))} → {e(CITY.get(d, d))}</p>
<h1 style="margin:8px 0 0;font-size:30px;color:#b4552d">{e(_twd(fare['price']))}</h1>
{usd}
<p style="margin:12px 0 0;font-size:15px">已低於你的目標價 {e(_twd(target))}。</p>
<p style="margin:16px 0 0;font-size:14px;color:#5b6b78">航空公司：{e(str(fare.get('airline') or '—'))}<br>
去程 {e(_day(fare.get('depart_date')))}　回程 {e(_day(fare.get('return_date')))}</p>
<p style="margin:24px 0 0"><a href="{e(booking_url(route, fare, marker))}"
 style="display:inline-block;background:#b4552d;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:bold">立即訂購</a></p>
<p style="margin:24px 0 0;font-size:12px;color:#8a97a3">票價隨時變動，以訂購頁面顯示為準。<br>Flight Price Notifier</p>
</div></body></html>"""


# ---------- dedup ----------
def should_send(pk, new_price):
    rows = _history.query(KeyConditionExpression=Key("pk").eq(pk), ScanIndexForward=False, Limit=1).get("Items", [])
    if not rows:
        return True, "first alert"
    last = rows[0]
    last_at = datetime.fromisoformat(last["sent_at"])
    if datetime.now(timezone.utc) - last_at >= timedelta(hours=FLOOR_HOURS):
        return True, f"last alert older than {FLOOR_HOURS:g}h"
    last_price = float(last.get("price", 0))
    if last_price and (new_price <= last_price * (1 - REALERT_PCT / 100) or last_price - new_price >= REALERT_ABS):
        return True, f"big drop {last_price:g} -> {new_price:g}"
    return False, f"last alert at {last['sent_at']} for {last_price:g}"


# ---------- send ----------
def send_email(cfg, to, subj, html_body, text_body):
    payload = {"from": cfg["from"], "to": [to], "subject": subj, "html": html_body, "text": text_body}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + cfg["api_key"],
                                          "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code == 429 or e.code >= 500:
            raise Transient(f"resend {e.code}: {body}")
        return e.code, body
    except (urllib.error.URLError, TimeoutError) as e:
        raise Transient(f"resend network error: {e}")


def process(msg):
    email, route = msg["email"], msg["route"]
    fare = msg["cheapest"]
    price = float(fare["price"])
    pk = f"{email}#{route}"

    ok, why = should_send(pk, price)
    if not ok:
        print(f"skipped (deduped) {pk}: {why}")
        return
    usd = (msg.get("cheapest_usd") or {}).get("price")
    marker = _marker()
    cfg = _secret("flight/resend")
    status, body = send_email(cfg, email, subject(route, fare),
                              render_html(route, fare, msg["target_price"], usd, marker),
                              render_text(route, fare, msg["target_price"], usd, marker))
    if 200 <= status < 300:
        _history.put_item(Item={"pk": pk, "sent_at": datetime.now(timezone.utc).isoformat(), "email": email,
                                "route": route, "price": Decimal(str(fare["price"])), "currency": "TWD"})
        print(f"sent {pk} at {_twd(price)} ({why}): {body}")
    else:
        print(f"dropped {pk}: permanent Resend error {status}: {body}")


def handler(event, context):
    failures = []
    for rec in event.get("Records", []):
        try:
            process(json.loads(rec["body"]))
        except Transient as e:
            print(f"retry later {rec.get('messageId')}: {e}")
            failures.append({"itemIdentifier": rec["messageId"]})
        except (KeyError, ValueError, TypeError) as e:
            print(f"dropped malformed message {rec.get('messageId')}: {e!r}")
    return {"batchItemFailures": failures}
