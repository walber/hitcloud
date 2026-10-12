# Implementation Plan: Page-View Counter

## Overview

Implement a serverless page-view counter on AWS using Python CDK and Lambda. The plan progresses from project scaffolding through infrastructure provisioning to the Lambda handler and browser integration snippet, wiring everything together in a deployable CDK stack.

---

## Tasks

- [x] 1. Scaffold CDK project structure
  - Create `app.py`, `cdk.json`, and `requirements.txt` at the project root
  - Create `hitcloud/__init__.py` and `hitcloud/hitcloud_stack.py` with an empty `HitCloudStack` class
  - Create `lambda/handler.py` as an empty placeholder
  - Pin CDK and constructs versions in `requirements.txt`
  - _Requirements: 6.1, 6.2_

- [x] 2. Implement the Hit Handler Lambda
  - [x] 2.1 Write `lambda/handler.py`
    - Import `json`, `os`, `boto3`; initialise the DynamoDB resource and `TABLE_NAME` env var outside the handler
    - Implement the single `try/except Exception` block with the atomic `UpdateItem` call (`ADD #count :inc`, `ReturnValues="UPDATED_NEW"`)
    - Build the shared `headers` dict (`Content-Type`, `Access-Control-Allow-Origin: *`, `Access-Control-Allow-Methods: POST, OPTIONS`) before the try block so it is available in both branches
    - Return HTTP 200 + `{"count": N}` on success; HTTP 500 + `{"error": "Internal server error"}` on failure
    - Emit a structured JSON log entry via `print(json.dumps(...))` in both branches (`{"status": "ok", "count": N}` / `{"status": "error", "message": "..."}`)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 4.1, 4.3_

  - [ ]* 2.2 Write property test — Property 1: CORS headers always present
    - Using `pytest` + `unittest.mock`, patch `boto3.resource` and drive the handler with a mock DynamoDB that alternates between a successful response and raising `ClientError`
    - Assert that both response dicts contain `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Methods: POST, OPTIONS` in their `headers`
    - **Property 1: CORS headers are always present**
    - **Validates: Requirements 1.3, 1.4**

  - [ ]* 2.3 Write property test — Property 2: Successful increment returns the DynamoDB count
    - Use `hypothesis` to generate integers `N ≥ 1`; mock DynamoDB to return `{"Attributes": {"count": Decimal(N)}}`
    - Assert `statusCode == 200` and `json.loads(body) == {"count": N}`
    - **Property 2: Successful increment returns the DynamoDB count**
    - **Validates: Requirements 2.3, 2.4, 2.5**

  - [ ]* 2.4 Write property test — Property 3: Counter Item key is always "hits"
    - Capture the `Key` argument passed to `update_item` via a `MagicMock`
    - Assert `Key == {"id": "hits"}` for every invocation
    - **Property 3: Counter Item key is always "hits"**
    - **Validates: Requirements 3.4**

  - [ ]* 2.5 Write property test — Property 4: DynamoDB errors always produce HTTP 500
    - Use `hypothesis` to generate exception types from `{ClientError, EndpointResolutionError, ParamValidationError, Exception}`; mock `update_item` to raise them
    - Assert `statusCode == 500` and `json.loads(body) == {"error": "Internal server error"}`
    - **Property 4: DynamoDB errors always produce HTTP 500**
    - **Validates: Requirements 4.1**

  - [ ]* 2.6 Write property test — Property 5: Every invocation produces a structured log entry
    - Capture stdout (or use `capfd`) across both success and failure paths
    - Assert that exactly one line is printed per invocation and that `json.loads(line)` contains a `status` field equal to `"ok"` or `"error"`
    - **Property 5: Every invocation produces a structured log entry**
    - **Validates: Requirements 4.3**

- [x] 3. Checkpoint — Handler tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement `HitCloudStack` in CDK
  - [x] 4.1 Declare the Counter Table
    - Instantiate `aws_dynamodb.Table` with PK `id` (STRING) and `PAY_PER_REQUEST` billing
    - _Requirements: 3.1, 3.2_

  - [x] 4.2 Declare the Hit Handler Lambda function
    - Instantiate `aws_lambda.Function` with runtime Python 3.12, handler `handler.handler`, code from `lambda/`, and env var `TABLE_NAME` set to `table.table_name`
    - _Requirements: 6.1, 6.2_

  - [x] 4.3 Apply least-privilege IAM grants
    - Call `table.grant(hit_handler, "dynamodb:UpdateItem")` — do NOT call `table.grant_read_write_data`
    - Add an inline policy statement granting `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` scoped to `arn:aws:logs:*:*:*`
    - _Requirements: 5.1, 5.2, 5.3, 5.5_

  - [x] 4.4 Declare the HTTP API and wire the route
    - Instantiate `aws_apigatewayv2.HttpApi` with `cors_preflight` allowing all origins (`*`), methods (`POST`, `OPTIONS`), and auto-deploy
    - Add a `POST /hits` route using `HttpLambdaIntegration`
    - Grant API Gateway `lambda:InvokeFunction` on the hit handler
    - Add a `CfnOutput` named `HitsApiUrl` exporting `http_api.url`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 5.4, 6.5_

  - [x] 4.5 Seed the Counter Item with an `AwsCustomResource`
    - Create an `AwsCustomResource` that calls `dynamodb:PutItem` with `{"id": {"S": "hits"}, "count": {"N": "0"}}` on `CREATE`; use `AwsSdkCall` with `ignore_error_codes_matching` to make it idempotent on subsequent deploys
    - _Requirements: 3.3_

- [x] 5. Checkpoint — CDK stack synthesises cleanly
  - Run `cdk synth` (or `cdk ls`) and confirm zero errors; ask the user if questions arise.

- [x] 6. Add browser integration snippet to README
  - [x] 6.1 Write `README.md`
    - Deployment section: prerequisites, `pip install -r requirements.txt`, `cdk bootstrap`, `cdk deploy`, expected `HitsApiUrl` output
    - Testing section: `curl -X POST <HitsApiUrl>/hits` and expected JSON response
    - Cleanup section: `cdk destroy`
    - Browser integration section: include the HTML `<span id="hit-count">` + `<script>` fetch snippet; instruct replacing `<HitsApiUrl>` with the CDK output value
    - Service limits section: Lambda (1 000 concurrent), API Gateway (10 000 RPS), DynamoDB on-demand
    - _Requirements: 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 8.3_

- [x] 7. Final checkpoint — Full stack wired and all tests pass
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (Properties 1–5 from the design)
- Unit/property tests live in `tests/` and use `pytest` + `hypothesis` + `unittest.mock`
- The CDK project root is `hitcloud/` per the design's infrastructure layout

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "2.5", "2.6", "4.2"] },
    { "id": 3, "tasks": ["4.3", "4.4"] },
    { "id": 4, "tasks": ["4.5"] },
    { "id": 5, "tasks": ["6.1"] }
  ]
}
```
