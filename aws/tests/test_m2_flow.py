"""Offline end-to-end test of the M2 Lambdas with in-memory fakes for DynamoDB, SQS and Secrets Manager.

Run: python3 aws/tests/test_m2_flow.py
"""
import base64, importlib.util, json, re, sys, types, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

LAMBDAS = Path(__file__).resolve().parents[1] / "lambdas"
TS = "%Y-%m-%dT%H:%M:%SZ"
SECRETS = {"flight/ecpay": {"merchant_id": "3002607", "hash_key": "pwFHCqoQZGmho4w6", "hash_iv": "EkRm7iFT261dpevs",
                            "env": "stage", "amount": "300"},
           "flight/resend": {"api_key": "re_test", "from": "onboarding@resend.dev"},
           "flight/supabase": {"url": "https://x.supabase.co", "publishable_key": "sb_publishable_x"}}
TABLES, QUEUES = {}, {}


# ---------------- fakes ----------------
class FakeTable:
    def __init__(self, name):
        self.name, self.rows = name, {}

    def _k(self, key):
        return tuple(sorted(key.items()))

    def get_item(self, Key):
        r = self.rows.get(self._k(Key))
        return {"Item": dict(r)} if r else {}

    def put_item(self, Item):
        k = {"subscriptions": ("email", "route"), "notification_history": ("pk", "sent_at")}[self.name]
        self.rows[self._k({x: Item[x] for x in k})] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ConditionExpression=None):
        row = self.rows.setdefault(self._k(Key), dict(Key))
        if ConditionExpression:
            m = re.match(r"(\w+) = (:\w+)", ConditionExpression)
            assert row.get(m.group(1)) == ExpressionAttributeValues[m.group(2)], "condition failed"
        for part in re.split(r",\s*(?![^()]*\))", UpdateExpression.replace("SET ", "", 1)):
            field, expr = [x.strip() for x in part.split("=", 1)]
            m = re.match(r"if_not_exists\((\w+),\s*(:\w+)\)", expr)
            row[field] = row.get(m.group(1), ExpressionAttributeValues[m.group(2)]) if m else ExpressionAttributeValues[expr]

    def scan(self, FilterExpression=None, **kw):
        items = [dict(r) for r in self.rows.values()]
        if FilterExpression is not None:
            items = [r for r in items if FilterExpression(r)]
        return {"Items": items}

    def query(self, KeyConditionExpression, ScanIndexForward=True, Limit=None, **kw):
        field, value = KeyConditionExpression
        items = sorted([dict(r) for r in self.rows.values() if r.get(field) == value], key=lambda r: r.get("sent_at", ""),
                       reverse=not ScanIndexForward)
        return {"Items": items[:Limit] if Limit else items}


class FakeClient:
    def __init__(self, svc):
        self.svc = svc

    def get_secret_value(self, SecretId):
        return {"SecretString": json.dumps(SECRETS[SecretId])}

    def get_queue_url(self, QueueName):
        return {"QueueUrl": QueueName}

    def send_message(self, QueueUrl, MessageBody):
        QUEUES.setdefault(QueueUrl, []).append(json.loads(MessageBody))


class Cond:
    def __init__(self, name):
        self.name = name

    def eq(self, v):
        if self.kind == "key":
            return (self.name, v)
        return lambda r: r.get(self.name) == v


def install_fakes():
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda svc: FakeClient(svc)
    boto3.resource = lambda svc: types.SimpleNamespace(Table=lambda n: TABLES.setdefault(n, FakeTable(n)))
    cond = types.ModuleType("boto3.dynamodb.conditions")
    cond.Key = type("Key", (Cond,), {"kind": "key"})
    cond.Attr = type("Attr", (Cond,), {"kind": "attr"})
    sys.modules.update({"boto3": boto3, "boto3.dynamodb": types.ModuleType("boto3.dynamodb"),
                        "boto3.dynamodb.conditions": cond})


def load(name):
    spec = importlib.util.spec_from_file_location(name, LAMBDAS / name / "index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------- helpers ----------------
def form_event(params, b64=True, api=True):
    body = urllib.parse.urlencode(params)
    ev = {"body": base64.b64encode(body.encode()).decode() if b64 else body, "isBase64Encoded": b64}
    if api:
        ev["requestContext"] = {"http": {"method": "POST"}}
    return ev


def signed_callback(mod, **fields):
    p = {"MerchantID": "3002607", "MerchantTradeNo": "", "RtnCode": "1", "RtnMsg": "交易成功", "PeriodType": "M",
         "Frequency": "1", "ExecTimes": "999", "Amount": "300", "Gwsr": "", "ProcessDate": "2026/10/26 12:00:00",
         "AuthCode": "777777", "FirstAuthAmount": "300", "TotalSuccessTimes": "1", "SimulatePaid": "0",
         "CustomField1": "", "CustomField2": "", "CustomField3": "", "CustomField4": ""}
    p.update(fields)
    p["CheckMacValue"] = mod.gen_cmv(p, SECRETS["flight/ecpay"]["hash_key"], SECRETS["flight/ecpay"]["hash_iv"])
    return p


def check(label, cond):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        global FAILED
        FAILED += 1


FAILED = 0


def main():
    import os
    os.environ.update({"API_BASE": "https://api.example.com", "SITE_URL": "https://site.example.com"})
    install_fakes()
    save, ret, per, res, cancel, parser, status = (load(n) for n in (
        "save_subscription", "ecpay_return", "ecpay_period", "ecpay_result", "cancel_subscription", "parser", "status_notification"))
    subs = TABLES["subscriptions"]
    email, route = "you@example.com", "TPE-TYO"
    key = {"email": email, "route": route}

    # 1. subscribe -> pending_payment + signed cashier form
    out = save.handler({"body": json.dumps({"email": email, "plan_name": "tokyo", "target_price": 8000})}, None)
    row = subs.get_item(Key=key)["Item"]
    check("subscribe returns text/html", out["headers"]["Content-Type"].startswith("text/html"))
    check("row is pending_payment with a <=20 char trade no", row["subscription_status"] == "pending_payment"
          and 0 < len(row["merchant_trade_no"]) <= 20)
    fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', out["body"]))
    fields = {k: v.replace("&amp;", "&") for k, v in fields.items()}
    check("form posts to the stage cashier", "payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5" in out["body"])
    check("form CheckMacValue verifies", ret.verify_cmv(fields, "pwFHCqoQZGmho4w6", "EkRm7iFT261dpevs"))
    check("TotalAmount == PeriodAmount == 300, monthly x999", fields["TotalAmount"] == fields["PeriodAmount"] == "300"
          and (fields["PeriodType"], fields["Frequency"], fields["ExecTimes"]) == ("M", "1", "999"))
    check("CustomField1/2 = email/route, OrderResultURL -> redirect Lambda",
          (fields["CustomField1"], fields["CustomField2"]) == (email, route) and fields["OrderResultURL"].endswith("/ecpay-result"))
    check("auto-submit script present", "document.forms[0].submit()" in out["body"])

    # unauthenticated API Gateway call is refused
    out = save.handler({"requestContext": {}, "headers": {}, "body": json.dumps({"email": email, "plan_name": "tokyo",
                                                                                   "target_price": 1})}, None)
    check("API call without a Supabase token -> 401", out["statusCode"] == 401)

    # 2. parser skips the unpaid row
    parser.fetch_cheapest = lambda o, d, m, t, c: {"price": 7500, "currency": c.upper(), "airline": "TR",
                                                   "depart_date": "2026-11-03", "return_date": "2026-11-07"}
    parser._token = "t"
    r = parser.handler({"origin": "TPE", "destination": "TYO", "route": route}, None)
    check("parser: pending_payment not enqueued", r["matched"] == 0 and r["skipped_unpaid"] == 1)

    trade = row["merchant_trade_no"]
    # 3. tampered + wrong-merchant + simulate callbacks do nothing
    bad = signed_callback(ret, MerchantTradeNo=trade, CustomField1=email, CustomField2=route)
    bad["RtnCode"] = "1 "
    out = ret.handler(form_event(bad), None)
    check("tampered callback -> 0|CheckMacValueInvalid 400", out["statusCode"] == 400 and out["body"].startswith("0|"))
    out = ret.handler(form_event(signed_callback(ret, MerchantTradeNo=trade, CustomField1=email, CustomField2=route,
                                                 SimulatePaid="1")), None)
    check("SimulatePaid=1 -> 1|OK but not active", out["body"] == "1|OK"
          and subs.get_item(Key=key)["Item"]["subscription_status"] == "pending_payment")

    # 4. real first charge -> active + welcome event; plain-text 1|OK
    QUEUES.clear()
    cb = signed_callback(ret, MerchantTradeNo=trade, CustomField1=email, CustomField2=route)
    out = ret.handler(form_event(cb), None)
    row = subs.get_item(Key=key)["Item"]
    check("ReturnURL -> 1|OK text/plain", out["body"] == "1|OK" and out["headers"]["Content-Type"].startswith("text/plain"))
    check("row active with current_period_end in Z format ~1 month out", row["subscription_status"] == "active"
          and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["current_period_end"])
          and 27 <= (datetime.strptime(row["current_period_end"], TS) - datetime.now(timezone.utc).replace(tzinfo=None)).days <= 31)
    check("welcome event enqueued once", [m["event_type"] for m in QUEUES.get("flight-status-queue", [])] == ["welcome"])
    ret.handler(form_event(cb), None)  # ECPay resend
    check("resend is idempotent (no second welcome)", len(QUEUES["flight-status-queue"]) == 1)

    # 5. paid user updates target in place (JSON, no re-payment)
    out = save.handler({"body": json.dumps({"email": email, "plan_name": "tokyo", "target_price": 9000})}, None)
    row = subs.get_item(Key=key)["Item"]
    check("active user target update -> JSON, still active, same trade no", out["headers"]["Content-Type"] == "application/json"
          and row["subscription_status"] == "active" and int(row["target_price"]) == 9000 and row["merchant_trade_no"] == trade)

    # 6. parser serves the active row
    r = parser.handler({"origin": "TPE", "destination": "TYO", "route": route}, None)
    check("parser: active row enqueued", r["matched"] == 1)

    # 7. renewal extends the period; failures count up and expire at 6
    before = row["current_period_end"]
    out = per.handler(form_event(signed_callback(per, MerchantTradeNo=trade, CustomField1=email, CustomField2=route,
                                                 TotalSuccessTimes="2")), None)
    after = subs.get_item(Key=key)["Item"]["current_period_end"]
    check("PeriodReturnURL success -> 1|OK and period extended", out["body"] == "1|OK" and after > before)
    per.handler(form_event(signed_callback(per, MerchantTradeNo=trade, CustomField1=email, CustomField2=route,
                                           RtnCode="10100058", RtnMsg="fail")), None)
    check("one failed renewal does NOT expire", subs.get_item(Key=key)["Item"]["subscription_status"] == "active")

    # 8. status email consumer: welcome renders + guards duplicates
    sent = []
    status.send_email = lambda cfg, to, s, h, t: (sent.append((to, s)), (200, '{"id":"x"}'))[1]
    msgs = QUEUES["flight-status-queue"]
    ev = {"Records": [{"messageId": "1", "body": json.dumps(msgs[0])}, {"messageId": "2", "body": json.dumps(msgs[0])}]}
    status.handler(ev, None)
    check("welcome email sent exactly once", len(sent) == 1 and "訂閱成功" in sent[0][1])

    # 9. cancel -> ECPay Cancel called, row cancelled with period kept, cancel event
    calls = []
    cancel.ecpay_cancel = lambda cfg, t: (calls.append(t), {"RtnCode": "1", "RtnMsg": "OK"})[1]
    keep = subs.get_item(Key=key)["Item"]["current_period_end"]
    out = cancel.handler({"body": json.dumps({"email": email, "route": route})}, None)
    row = subs.get_item(Key=key)["Item"]
    check("cancel -> CreditCardPeriodAction called with the trade no", calls == [trade])
    check("cancel -> cancelled (not expired), period kept", row["subscription_status"] == "cancelled"
          and row["current_period_end"] == keep)
    check("cancel event enqueued", QUEUES["flight-status-queue"][-1]["event_type"] == "cancel")
    status.handler({"Records": [{"messageId": "3", "body": json.dumps(QUEUES["flight-status-queue"][-1])}]}, None)
    check("cancel email sent", "已取消訂閱" in sent[-1][1])

    # 10. grace: still served; cancelled user can update target in place
    r = parser.handler({"origin": "TPE", "destination": "TYO", "route": route}, None)
    check("parser: cancelled-in-grace still enqueued", r["matched"] == 1)
    out = save.handler({"body": json.dumps({"email": email, "plan_name": "tokyo", "target_price": 8500})}, None)
    check("grace user target update -> JSON, stays cancelled", out["headers"]["Content-Type"] == "application/json"
          and subs.get_item(Key=key)["Item"]["subscription_status"] == "cancelled")

    # 11. grace lapses -> parser expires lazily and stops alerting
    subs.update_item(Key=key, UpdateExpression="SET current_period_end=:e",
                     ExpressionAttributeValues={":e": (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)).strftime(TS)})
    r = parser.handler({"origin": "TPE", "destination": "TYO", "route": route}, None)
    check("parser: grace lapsed -> expired, not enqueued", r["matched"] == 0 and r["expired_after_grace"] == 1
          and subs.get_item(Key=key)["Item"]["subscription_status"] == "expired")

    # 12. expired user re-subscribes -> new pending order (fresh trade no) + cashier form
    out = save.handler({"body": json.dumps({"email": email, "plan_name": "tokyo", "target_price": 8000})}, None)
    row = subs.get_item(Key=key)["Item"]
    check("expired -> re-subscribe gives a new pending_payment order", out["headers"]["Content-Type"].startswith("text/html")
          and row["subscription_status"] == "pending_payment" and row["merchant_trade_no"] != trade)

    # 13. 6 consecutive failed renewals expire an active row
    subs.update_item(Key=key, UpdateExpression="SET subscription_status=:a", ExpressionAttributeValues={":a": "active"})
    for i in range(6):
        per.handler(form_event(signed_callback(per, MerchantTradeNo=row["merchant_trade_no"], CustomField1=email,
                                               CustomField2=route, RtnCode="10100058")), None)
    check("6th consecutive failed renewal -> expired", subs.get_item(Key=key)["Item"]["subscription_status"] == "expired")

    # 14. OrderResultURL redirect
    out = res.handler(form_event({"RtnCode": "1"}), None)
    check("OrderResultURL -> 302 /app?purchase=success", out["statusCode"] == 302
          and out["headers"]["Location"] == "https://site.example.com/app?purchase=success")

    # 15. legacy M1 row (no status) is skipped by the parser
    subs.put_item({"email": "legacy@example.com", "route": route, "target_price": 99999})
    r = parser.handler({"origin": "TPE", "destination": "TYO", "route": route}, None)
    check("parser: legacy row without status not enqueued", r["matched"] == 0)

    # helper copies are identical everywhere
    blocks = {n: re.search(r"# --- ECPay CheckMacValue ---.*?# --- end CheckMacValue ---", (LAMBDAS / n / "index.py").read_text(), re.S).group(0)
              for n in ("ecpay_return", "ecpay_period", "save_subscription", "cancel_subscription")}
    check("CheckMacValue helper identical in all 4 Lambdas", len(set(blocks.values())) == 1)
    auths = {n: re.search(r"# --- Supabase auth ---.*?# --- end Supabase auth ---", (LAMBDAS / n / "index.py").read_text(), re.S).group(0)
             for n in ("save_subscription", "list_subscriptions", "cancel_subscription")}
    check("Supabase auth helper identical in all 3 Lambdas", len(set(auths.values())) == 1)

    print(f"\n{'ALL PASSED' if not FAILED else f'{FAILED} FAILED'}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
