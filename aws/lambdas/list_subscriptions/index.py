import json
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Key

ddb = boto3.resource("dynamodb").Table("subscriptions")


def _plain(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def handler(event, context):
    # No auth in M1: trusts the client-supplied email. Production would verify the Supabase JWT here.
    email = ((event.get("queryStringParameters") or {}).get("email") or "").strip().lower()
    if not email:
        return {"statusCode": 400, "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "email is required"})}
    items = ddb.query(KeyConditionExpression=Key("email").eq(email)).get("Items", [])
    rows = [{k: _plain(v) for k, v in it.items()} for it in items]
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"subscriptions": rows})}
