"""flight-ecpay-result: ECPay OrderResultURL. ECPay returns the browser with a POST, which a static
SPA answers with 405, so this only redirects (302) back to /app. It never activates anything:
activation happens in the server-to-server ReturnURL callback."""
import base64, os, urllib.parse


def handler(event, context):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", errors="replace")
    params = urllib.parse.parse_qs(raw, keep_blank_values=True)
    ok = (params.get("RtnCode") or [""])[0] == "1"
    site = os.environ.get("SITE_URL", "").rstrip("/")
    return {"statusCode": 302, "headers": {"Location": f"{site}/app?purchase={'success' if ok else 'failed'}"}, "body": ""}
