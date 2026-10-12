# Design Document

## Overview

A serverless page-view counter built on AWS, provisioned entirely with the AWS CDK in Python. A single Lambda function performs an atomic DynamoDB `UpdateItem` and returns the updated count via API Gateway HTTP API. The solution has no server management, scales automatically, and is deployable and removable with a single CDK command.

---

## Architecture

```
Browser
  │
  │  POST /hits  (HTTPS)
  ▼
API Gateway HTTP API
  │
  │  Lambda proxy integration
  ▼
Hit Handler (Lambda / Python)
  │
  │  UpdateItem (atomic ADD)
  ▼
Counter Table (DynamoDB)
```

All resources live in a single CDK stack. API Gateway triggers the Lambda on every `POST /hits` (and passes `OPTIONS` through for CORS preflight). The Lambda issues a single `UpdateItem` call with an `ADD` expression, receives the updated count, and returns it in the response body.

---

## Components

### 1. CDK Stack — `HitCloudStack`

Responsible for declaring all AWS resources and their relationships.

| Resource | CDK Construct | Key configuration |
|---|---|---|
| Counter Table | `aws_dynamodb.Table` | PK `id` (String), `PAY_PER_REQUEST` billing |
| Hit Handler | `aws_lambda.Function` | Python 3.12, env var `TABLE_NAME` |
| Counter API | `aws_apigatewayv2.HttpApi` | CORS `*`, auto-deploy |
| Lambda integration | `aws_apigatewayv2_integrations.HttpLambdaIntegration` | Proxy |
| Route | `POST /hits` | — |
| Output | `CfnOutput` | `HitsApiUrl` |
| Custom resource | `custom_resources.AwsCustomResource` | Seeds Counter Item on first deploy |

IAM permissions are granted with the CDK grant methods:

```python
table.grant(hit_handler, "dynamodb:UpdateItem")
hit_handler.add_to_role_policy(logs_policy_statement)
```

### 2. Hit Handler — `lambda/handler.py`

A single Python function. It is the only component that contains application logic.

Responsibilities:
- Receive the Lambda event from API Gateway
- Call DynamoDB `UpdateItem` with an atomic `ADD` expression
- Return `{"count": N}` with HTTP 200 on success
- Return `{"error": "Internal server error"}` with HTTP 500 on failure
- Emit a structured JSON log entry for every invocation

### 3. Counter Table

A single DynamoDB table with one item. No secondary indexes, no streams.

```
Table: HitCloudCounter
  Partition key: id (String)
  Billing: PAY_PER_REQUEST

Item:
  { "id": "hits", "count": 0 }   ← seeded by custom resource on first deploy
```

### 4. Counter API

An Amazon API Gateway HTTP API with two routes:

| Method | Path | Handler |
|---|---|---|
| `POST` | `/hits` | Hit Handler (Lambda proxy) |
| `OPTIONS` | `/hits` | Handled automatically by HTTP API CORS config |

CORS is configured at the API level with `allow_origins=["*"]`.

---

## Interfaces

### Lambda Event (from API Gateway)

The Hit Handler does not use the event body or path parameters. It only needs to know it was invoked. The event is a standard API Gateway v2 proxy event dict.

### Lambda Response

```python
{
    "statusCode": 200,
    "headers": {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS"
    },
    "body": '{"count": 42}'
}
```

Error response:

```python
{
    "statusCode": 500,
    "headers": {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS"
    },
    "body": '{"error": "Internal server error"}'
}
```

### DynamoDB UpdateItem call

```python
response = table.update_item(
    Key={"id": "hits"},
    UpdateExpression="ADD #count :inc",
    ExpressionAttributeNames={"#count": "count"},
    ExpressionAttributeValues={":inc": 1},
    ReturnValues="UPDATED_NEW",
)
count = int(response["Attributes"]["count"])
```

### CloudWatch Log Entry

Structured JSON emitted via `print()` or `json.dumps()` on every invocation:

Success:
```json
{ "status": "ok", "count": 42 }
```

Error:
```json
{ "status": "error", "message": "<exception string>" }
```

---

## Data Models

### Counter Item

```
{
  "id":    String  — always "hits" (partition key)
  "count": Number  — monotonically increasing integer, starts at 0
}
```

No other attributes are written. The `ADD` expression initialises `count` to `0` if the item does not yet exist (DynamoDB behavior), but the CDK custom resource seeds the item explicitly so the first response always returns `1`.

---

## Error Handling

| Scenario | Handling |
|---|---|
| DynamoDB `ClientError` / `BotoCoreError` | Caught in `except`, returns HTTP 500 + error JSON, logs error |
| DynamoDB returns unexpected `Attributes` shape | `KeyError` caught by the same except block |
| API Gateway route not found | HTTP API returns 404 natively; no Lambda involved |
| OPTIONS preflight | HTTP API CORS config answers automatically; no Lambda invoked |

The Lambda handler uses a single `try/except Exception` block — broad enough to catch any DynamoDB or serialization failure, tight enough to not suppress `SystemExit` / `KeyboardInterrupt`.

```python
import json
import os
import boto3

dynamodb = boto3.resource("dynamodb")
TABLE_NAME = os.environ["TABLE_NAME"]

def handler(event, context):
    table = dynamodb.Table(TABLE_NAME)
    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
    }
    try:
        response = table.update_item(
            Key={"id": "hits"},
            UpdateExpression="ADD #count :inc",
            ExpressionAttributeNames={"#count": "count"},
            ExpressionAttributeValues={":inc": 1},
            ReturnValues="UPDATED_NEW",
        )
        count = int(response["Attributes"]["count"])
        print(json.dumps({"status": "ok", "count": count}))
        return {
            "statusCode": 200,
            "headers": headers,
            "body": json.dumps({"count": count}),
        }
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return {
            "statusCode": 500,
            "headers": headers,
            "body": json.dumps({"error": "Internal server error"}),
        }
```

---

## Infrastructure Layout

```
hitcloud/
├── app.py                   # CDK app entry point
├── cdk.json
├── requirements.txt         # CDK + constructs dependencies
├── hitcloud/
│   ├── __init__.py
│   └── hitcloud_stack.py    # HitCloudStack definition
└── lambda/
    └── handler.py           # Hit Handler
```

---

## Browser Integration Snippet

```html
<!-- Place in the Coming Soon page -->
<span id="hit-count">…</span>

<script>
  fetch("https://<HitsApiUrl>/hits", { method: "POST" })
    .then(function(res) { return res.json(); })
    .then(function(data) {
      document.getElementById("hit-count").textContent = data.count;
    })
    .catch(function() {
      // silently ignore — counter is non-critical
    });
</script>
```

Replace `<HitsApiUrl>` with the value from the `cdk deploy` output.

---

## Scalability Notes

The solution is fully serverless. Known AWS default limits:

| Service | Limit | Notes |
|---|---|---|
| Lambda | 1,000 concurrent executions per region | Requestable increase |
| API Gateway HTTP API | 10,000 RPS per account | Requestable increase |
| DynamoDB on-demand | No pre-set throughput limit; scales on demand | Burst limits apply for new tables |

No architectural changes are needed for expected campaign traffic. If the campaign reaches millions of concurrent visitors, a sharded counter (multiple DynamoDB items + aggregation) should be considered — but that is out of scope for this release.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: CORS headers are always present

*For any* invocation of the Hit Handler — whether the DynamoDB call succeeds or fails — the response object SHALL contain both `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Methods: POST, OPTIONS` headers.

**Validates: Requirements 1.3, 1.4**

---

### Property 2: Successful increment returns the DynamoDB count

*For any* integer value `N ≥ 1` returned by a mocked DynamoDB `UpdateItem` as the updated `count`, the Hit Handler SHALL return HTTP status 200 and a response body that deserialises to `{"count": N}`.

**Validates: Requirements 2.3, 2.4, 2.5**

---

### Property 3: Counter Item key is always "hits"

*For any* invocation of the Hit Handler, the DynamoDB `UpdateItem` call SHALL use exactly `{"id": "hits"}` as the `Key` argument — no other key value is ever used.

**Validates: Requirements 3.4**

---

### Property 4: DynamoDB errors always produce HTTP 500

*For any* exception raised by the DynamoDB client (e.g., `ClientError`, `EndpointResolutionError`, `ParamValidationError`), the Hit Handler SHALL return HTTP status 500 and a response body that deserialises to `{"error": "Internal server error"}`.

**Validates: Requirements 4.1**

---

### Property 5: Every invocation produces a structured log entry

*For any* invocation of the Hit Handler — regardless of whether it succeeds or fails — the handler SHALL emit exactly one structured JSON log entry containing a `status` field set to either `"ok"` or `"error"`.

**Validates: Requirements 4.3**
