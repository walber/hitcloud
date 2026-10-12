import json
import os
from contextvars import ContextVar

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Module-level DynamoDB resource — used for GET /count (retries acceptable for reads)
dynamodb = boto3.resource("dynamodb")
TABLE_NAME = os.environ["TABLE_NAME"]
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")


_request_origin = ContextVar("request_origin", default=None)


def _cors_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": _request_origin.get() or ALLOWED_ORIGIN,
        "Vary": "Origin",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Cache-Control": "no-store",
    }


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": _cors_headers(),
        "body": json.dumps(body),
    }


def _handle_post_hit() -> dict:
    """POST /hit — atomic increment, no retries to prevent double-count."""
    # Dedicated client with total_max_attempts=1 to prevent retry-induced double-increments
    # on this non-idempotent UpdateItem operation.
    ddb_client = boto3.client(
        "dynamodb",
        config=Config(retries={"total_max_attempts": 1, "mode": "standard"}),
    )
    try:
        result = ddb_client.update_item(
            TableName=TABLE_NAME,
            Key={"id": {"S": "hits"}},
            UpdateExpression="SET #count = if_not_exists(#count, :zero) + :one",
            ExpressionAttributeNames={"#count": "count"},
            ExpressionAttributeValues={":zero": {"N": "0"}, ":one": {"N": "1"}},
            ReturnValues="ALL_NEW",
        )
        count = int(result["Attributes"]["count"]["N"])
        print(json.dumps({"status": "ok"}))
        return _response(200, {"count": count})
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        print(json.dumps({"status": "error"}))
        return _response(503, {"error": "Service temporarily unavailable"})
    except Exception:
        print(json.dumps({"status": "error"}))
        return _response(503, {"error": "Service temporarily unavailable"})


def _handle_get_count() -> dict:
    """GET /count — strongly consistent read, never modifies counter."""
    table = dynamodb.Table(TABLE_NAME)
    try:
        result = table.get_item(
            Key={"id": "hits"},
            ConsistentRead=True,
        )
        item = result.get("Item")
        count = int(item["count"]) if item and "count" in item else 0
        print(json.dumps({"status": "ok"}))
        return _response(200, {"count": count})
    except ClientError:
        print(json.dumps({"status": "error"}))
        return _response(503, {"error": "Service temporarily unavailable"})
    except Exception:
        print(json.dumps({"status": "error"}))
        return _response(503, {"error": "Service temporarily unavailable"})


def _dispatch(event, context):
    method = event.get("httpMethod", "")
    path = event.get("path", "")

    if method == "OPTIONS":
        print(json.dumps({"status": "ok"}))
        return _response(200, {})

    if method == "POST" and path == "/hit":
        return _handle_post_hit()

    if method == "GET" and path == "/count":
        return _handle_get_count()

    print(json.dumps({"status": "error"}))
    return _response(405, {"error": "Method not allowed"})


def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    origin = headers.get("origin")
    allowed = [ALLOWED_ORIGIN, *json.loads(os.environ.get("EXTRA_ALLOWED_ORIGINS", "[]"))]
    token = _request_origin.set(origin if origin in allowed else ALLOWED_ORIGIN)
    try:
        return _dispatch(event, context)
    except Exception:
        print(json.dumps({"status": "error"}))
        return _response(503, {"error": "Service temporarily unavailable"})
    finally:
        _request_origin.reset(token)
