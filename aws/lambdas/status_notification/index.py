"""flight-status-notification: the ONE consumer for subscription status emails (flight-status-queue).

Routes on message["event_type"]: "welcome" (first payment) or "cancel" (subscription cancelled,
still valid until current_period_end). Sends once per (event, order) - guarded via
notification_history - through Resend. 429/5xx retry via SQS; other 4xx are dropped.
"""
import html, json, urllib.error, urllib.request
from datetime import datetime, timezone
import boto3
from boto3.dynamodb.conditions import Key

UA = "Mozilla/5.0 (compatible; flight-notifier/1.0)"
CITY = {"TPE": "台北", "TYO": "東京", "SEL": "首爾", "LON": "倫敦"}

_secrets = boto3.client("secretsmanager")
_history = boto3.resource("dynamodb").Table("notification_history")
_cache = {}


class Transient(Exception):
    pass


def _secret(name):
    if name not in _cache:
        _cache[name] = json.loads(_secrets.get_secret_value(SecretId=name)["SecretString"])
    return _cache[name]


def _route_title(route):
    o, d = route.split("-", 1)
    return f"{CITY.get(o, o)} → {CITY.get(d, d)}"


def _card(heading, lines):
    body = "".join(f'<p style="margin:10px 0 0;font-size:15px">{line}</p>' for line in lines)
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#faf6ee;font-family:Arial,Helvetica,sans-serif;color:#23394a">
<div style="max-width:480px;margin:0 auto;background:#ffffff;border:1px solid #eadfcb;border-radius:12px;padding:28px">
<h1 style="margin:0;font-size:22px;color:#b4552d">{heading}</h1>{body}
<p style="margin:24px 0 0;font-size:12px;color:#8a97a3">Flight Price Notifier</p>
</div></body></html>"""


def render(msg):
    e = html.escape
    title = _route_title(msg["route"])
    until = msg.get("current_period_end_date") or "—"
    if msg["event_type"] == "welcome":
        amount = msg.get("amount")
        target = msg.get("target_price")
        subject = f"訂閱成功：{title} 降價通知已啟用"
        lines = [f"謝謝你訂閱 {e(title)} 的機票降價通知。",
                 f"目標價：NT${int(target):,}" if target else "",
                 f"月費：NT${int(amount):,}，每月自動扣款" if amount else "",
                 f"本期有效至 {e(until)}。票價低於目標價時，我們會寄信通知你。"]
    else:
        subject = f"已取消訂閱：{title}"
        lines = [f"你已取消 {e(title)} 的機票降價通知，之後不會再自動扣款。",
                 f"已付費的這一期仍有效，{e(until)} 之前還是會收到降價通知。",
                 "想恢復的話，隨時可以在網站上重新訂閱。"]
    lines = [line for line in lines if line]
    text = "\n".join(lines) + "\n\n— Flight Price Notifier"
    return subject, _card(e(subject), lines), text


def send_email(cfg, to, subject, html_body, text_body):
    payload = {"from": cfg["from"], "to": [to], "subject": subject, "html": html_body, "text": text_body}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + cfg["api_key"],
                                          "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as ex:
        body = ex.read().decode(errors="replace")
        if ex.code == 429 or ex.code >= 500:
            raise Transient(f"resend {ex.code}: {body}")
        return ex.code, body
    except (urllib.error.URLError, TimeoutError) as ex:
        raise Transient(f"resend network error: {ex}")


def process(msg):
    kind = msg.get("event_type")
    if kind not in ("welcome", "cancel"):
        print("dropped unknown event_type:", kind)
        return
    email, route = msg["email"], msg["route"]
    pk = f"status#{kind}#{email}#{route}#{msg.get('merchant_trade_no', '')}"
    if _history.query(KeyConditionExpression=Key("pk").eq(pk), Limit=1).get("Items"):
        print(f"skipped (already sent) {pk}")
        return
    subject, html_body, text_body = render(msg)
    status, body = send_email(_secret("flight/resend"), email, subject, html_body, text_body)
    if 200 <= status < 300:
        _history.put_item(Item={"pk": pk, "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "email": email, "route": route, "event_type": kind})
        print(f"sent {kind} {email}#{route}: {body}")
    else:
        print(f"dropped {kind} {email}#{route}: permanent Resend error {status}: {body}")


def handler(event, context):
    failures = []
    for rec in event.get("Records", []):
        try:
            process(json.loads(rec["body"]))
        except Transient as ex:
            print(f"retry later {rec.get('messageId')}: {ex}")
            failures.append({"itemIdentifier": rec["messageId"]})
        except (KeyError, ValueError, TypeError) as ex:
            print(f"dropped malformed message {rec.get('messageId')}: {ex!r}")
    return {"batchItemFailures": failures}
