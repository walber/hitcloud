# Implementation Plan: Website Access Counter

## Overview

Migrate the existing HitCloud serverless counter into a production-ready deployable website. The implementation follows an infrastructure-first order: CDK project restructure → DynamoDB → Lambda → API Gateway → WAF → S3/CloudFront → ACM/Route 53 → CloudWatch → Frontend → Tests → Documentation. Each step produces runnable code that integrates into the previous step, with checkpoint tasks to validate progress incrementally.

Language: **Python 3.12** (backend + CDK) and **TypeScript** (frontend).

---

## Tasks

- [x] 1. Repository inspection and CDK project restructure
  - [x] 1.1 Read existing files and plan migration
    - Read `app.py`, `hitcloud/hitcloud_stack.py`, `lambda/handler.py`, `tests/test_handler.py`, `requirements.txt`, `cdk.json`
    - Identify all symbols that must be renamed or deleted before adding new code
    - Create `hitcloud/app_stack.py` as an empty module with a stub `AppStack(Stack)` class that passes `cdk synth` without errors
    - Delete `hitcloud/hitcloud_stack.py` (the old stack file)
    - Update `hitcloud/__init__.py` to export `AppStack` instead of `HitCloudStack`
    - Update `app.py` to import and instantiate `AppStack` from `hitcloud.app_stack`; remove all references to `HitCloudStack`
    - _Requirements: 1.1, 1.2_

  - [x] 1.2 Add configuration support to `cdk.json`
    - Replace existing `cdk.json` `context` block with the documented example keys: `environment`, `aws_account`, `api_burst_limit`, `api_rate_limit`, `waf_rate_limit`, `alarm_*`, `log_retention_days`; omit `domain_name` and `hosted_zone_id` so the no-custom-domain path is the default
    - Leave a commented-out block showing optional keys (`domain_name`, `hosted_zone_id`)
    - _Requirements: 1.2, 1.7_

- [x] 2. DynamoDB Counter Table
  - [x] 2.1 Implement DynamoDB table construct in `AppStack`
    - Inside `AppStack.__init__`, read `environment` context key (default `"dev"`); derive `is_production = env == "production"`
    - Provision `dynamodb.Table` with: partition key `id` (String), `BillingMode.PAY_PER_REQUEST`, `TableEncryption.AWS_MANAGED`, `point_in_time_recovery=True`
    - Set `deletion_protection=is_production` and `removal_policy=RETAIN` when production, `DESTROY` otherwise
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 2.2 Write infrastructure unit tests for DynamoDB table
    - In `tests/test_infrastructure.py` (new file), synthesise the AppStack template using `aws_cdk.assertions.Template`
    - Assert `PointInTimeRecoverySpecification.PointInTimeRecoveryEnabled = True`
    - Assert `BillingMode = "PAY_PER_REQUEST"`
    - _Requirements: 11.3_

- [x] 3. Lambda Hit Handler rewrite
  - [x] 3.1 Rewrite `lambda/handler.py`
    - Replace the existing single-purpose increment handler with the full two-route handler described in the design
    - Implement `_cors_headers()`, `_response()`, `_handle_post_hit()` (dedicated `boto3.client` with `total_max_attempts=1`), `_handle_get_count()` (module-level `boto3.resource`, `ConsistentRead=True`), and `handler()` dispatch
    - Ensure `Cache-Control: no-store` is present on all responses
    - Ensure `OPTIONS` → 200, unknown method/path → 405, DynamoDB errors → 503
    - Emit exactly one structured JSON log line per invocation containing `status` only
    - _Requirements: 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 4.2, 6.4, 6.5_

  - [x] 3.2 Write pytest unit tests for the Hit Handler
    - Update `tests/test_handler.py` to cover: `GET /count` returns `{"count": 0}` when no item; `GET /count` does not call `UpdateItem`; `POST /hit` calls `UpdateItem` with atomic expression and returns updated count; concurrent `POST /hit` via mocked atomic semantics does not lose increments; DynamoDB `ClientError` returns 503; unknown method returns 405
    - Use `unittest.mock.patch` to mock `boto3.resource` and `boto3.client`
    - _Requirements: 11.1_

  - [x] 3.3 Write Hypothesis property tests for the Hit Handler
    - In `tests/test_handler.py`, add Hypothesis strategies and property tests for:
      - **Property 1**: CORS headers present on every response path (validates Req 4.2)
      - **Property 2**: `Cache-Control: no-store` on every response (validates Req 6.5)
      - **Property 3**: POST /hit returns DynamoDB count value for any non-negative integer (validates Req 3.4)
      - **Property 4**: GET /count returns 0 when item absent (validates Req 3.6, 5.4)
      - **Property 5**: GET /count returns stored count for any non-negative integer (validates Req 3.6)
      - **Property 6**: GET /count never calls UpdateItem (validates Req 3.7)
      - **Property 7**: Counter item key is always `{"id": {"S": "hits"}}` (validates Req 3.4)
      - **Property 8**: DynamoDB throttle/transient errors produce HTTP 503 (validates Req 3.8)
      - **Property 9**: Any unexpected exception produces HTTP 503 (validates Req 3.8)
      - **Property 10**: Unknown HTTP methods produce HTTP 405 (validates Req 3.9)
    - _Requirements: 11.2_

- [x] 4. Checkpoint — Backend unit tests pass
  - Ensure `pytest tests/test_handler.py` runs green. Ask the user if any questions arise.

- [x] 5. Lambda construct and IAM wiring in `AppStack`
  - [x] 5.1 Add Lambda construct and CloudWatch log group to `AppStack`
    - Read `log_retention_days` context key (default 30)
    - Create `logs.LogGroup` scoped to the function's log group ARN
    - Create `_lambda.Function` with `runtime=PYTHON_3_12`, `handler="handler.handler"`, `code=Code.from_asset("lambda")`, env vars `TABLE_NAME` and `ALLOWED_ORIGIN`
    - _Requirements: 6.3, 6.4_

  - [x] 5.2 Grant least-privilege IAM permissions to Lambda
    - Call `table.grant(hit_handler, "dynamodb:UpdateItem", "dynamodb:GetItem")` — do NOT use broad grants
    - Add inline `PolicyStatement` for `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` scoped to log group ARN and `${logGroupArn}:*`
    - _Requirements: 6.1, 6.2_

  - [x] 5.3 Write infrastructure assertions for Lambda IAM role
    - In `tests/test_infrastructure.py`, assert that the IAM role policy JSON contains `dynamodb:UpdateItem` and `dynamodb:GetItem` but NOT `dynamodb:*`
    - _Requirements: 11.3_

- [x] 6. API Gateway REST API v1
  - [x] 6.1 Add `RestApi` construct to `AppStack`
    - Provision `apigw.RestApi` with `EndpointType.REGIONAL`, `StageOptions` for throttling (`api_burst_limit`, `api_rate_limit`), `logging_level=ERROR`, `data_trace_enabled=False`, `metrics_enabled=True`
    - Configure `default_cors_preflight_options` with `allow_origins=[website_url, "http://localhost:5173"]`, `allow_methods=["GET","POST","OPTIONS"]`, `allow_headers=["Content-Type"]`
    - Add `LambdaIntegration` (proxy=True) to `POST /hit` and `GET /count` resources
    - _Requirements: 3.1, 3.2, 4.1_

  - [x] 6.2 Configure API Gateway gateway responses with CORS headers
    - Add `add_gateway_response` for `DEFAULT_4XX`, `DEFAULT_5XX`, `THROTTLED`, `UNAUTHORIZED` with `Access-Control-Allow-Origin` and `Access-Control-Allow-Headers` response headers
    - _Requirements: 4.3_

  - [x] 6.3 Restrict Lambda invocation to API Gateway ARN
    - Call `hit_handler.add_permission("ApiGatewayInvoke", ...)` with `source_arn=api.arn_for_execute_api()`
    - _Requirements: 6.6_

- [x] 7. WAFv2 Web ACL
  - [x] 7.1 Add `CfnWebACL` construct to `AppStack`
    - Provision regional `wafv2.CfnWebACL` with default `allow` action, CloudWatch metrics enabled, sampled requests enabled
    - Add `AWSManagedRulesCommonRuleSet` managed rule at priority 1 with `none` override action
    - Add rate-based rule at priority 2 (block action) with `waf_rate_limit` threshold (default 1000) aggregated per IP
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 7.2 Associate WAF Web ACL with API Gateway stage
    - Add `CfnWebACLAssociation` with `resource_arn` pointing to the API Gateway stage ARN using `api.rest_api_id` and `env`
    - _Requirements: 3.3, 7.1_

  - [x] 7.3 Write infrastructure assertion for WAF association
    - In `tests/test_infrastructure.py`, assert that a `CfnWebACLAssociation` resource exists and references the correct stage ARN pattern
    - _Requirements: 11.3_

- [x] 8. S3 bucket and CloudFront distribution
  - [x] 8.1 Add private S3 bucket to `AppStack`
    - Provision `s3.Bucket` with `BlockPublicAccess.BLOCK_ALL`, `BucketEncryption.S3_MANAGED`, `versioned=True`, `removal_policy=RETAIN`
    - _Requirements: 2.1_

  - [x] 8.2 Configure CloudFront OAC and distribution
    - Create `cloudfront.S3OriginAccessControl` with `signing=Signing.SIGV4_ALWAYS`
    - Create `s3_origin` via `S3BucketOrigin.with_origin_access_control(bucket, oac)`
    - Build `ResponseHeadersPolicy` with HSTS (max-age 63072000), `X-Content-Type-Options`, `X-Frame-Options=DENY`, `Referrer-Policy`, and CSP `connect-src` restricted to the API URL
    - Create `short_cache` (TTL 60s) and `long_cache` (TTL 365d) `CachePolicy` constructs
    - Provision `cloudfront.Distribution` with default behaviour (short cache + security headers), additional behaviours for `*.js` and `*.css` (long cache), `/config.json` (short cache); `default_root_object="index.html"`; conditionally attach ACM certificate and custom domain names
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 8.3 Write infrastructure assertions for S3 and CloudFront OAC
    - In `tests/test_infrastructure.py`, assert S3 bucket has all four `BlockPublicAcls`/`BlockPublicPolicy`/`IgnorePublicAcls`/`RestrictPublicBuckets` set to `True`
    - Assert CloudFront distribution uses OAC (no `S3OriginConfig` with `OriginAccessIdentity`)
    - _Requirements: 11.3_

- [x] 9. ACM CertStack (optional, us-east-1)
  - [x] 9.1 Create `hitcloud/cert_stack.py` with `CertStack`
    - Implement `CertStack(Stack)` that reads `domain_name` and `hosted_zone_id` context keys, creates `route53.HostedZone.from_hosted_zone_attributes`, provisions `acm.Certificate` with DNS validation, and exports the certificate ARN as `CfnOutput(export_name="HitCloudCertificateArn")`
    - _Requirements: 9.1_

  - [x] 9.2 Wire CertStack conditionally in `app.py`
    - Update `app.py` to conditionally instantiate `CertStack` when both `domain_name` and `hosted_zone_id` context keys are present; pass `certificate=cert_stack.certificate` to `AppStack`, otherwise pass `certificate=None`
    - Update `AppStack.__init__` signature to accept optional `certificate` parameter and use it for the CloudFront distribution
    - _Requirements: 1.3, 1.4, 9.2, 9.3_

- [x] 10. CloudWatch alarms
  - [x] 10.1 Add four CloudWatch alarms to `AppStack`
    - Read alarm threshold context keys with defaults (lambda errors: 1, lambda throttles: 1, API 5xx: 5, DynamoDB errors: 1)
    - Create `cloudwatch.Alarm` for: `hit_handler.metric_errors()`, `hit_handler.metric_throttles()`, `api.metric_server_error()`, `table.metric_system_errors_for_operations()`, each with `evaluation_periods=1`, `treat_missing_data=NOT_BREACHING`
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 11. CloudFormation outputs and CDK stack completion
  - [x] 11.1 Add CloudFormation outputs to `AppStack`
    - Add `CfnOutput` for `WebsiteUrl` (`https://{domain_name or distribution.domain_name}`), `ApiUrl` (`api.url`), `DistributionId` (`distribution.distribution_id`), `TableName` (`table.table_name`)
    - Add `Tags.of(self).add("Environment", env)` to tag all resources
    - _Requirements: 1.5, 1.6_

  - [x] 11.2 Write infrastructure assertions for stack outputs and tags
    - In `tests/test_infrastructure.py`, assert all four `CfnOutput` keys are present in the synthesised template
    - Assert at least one resource carries the `Environment` tag
    - _Requirements: 1.5, 1.6, 11.3_

- [x] 12. Checkpoint — CDK synth and infrastructure tests pass
  - Run `cdk synth` to confirm zero synthesis errors. Run `pytest tests/test_infrastructure.py`. Ask the user if any questions arise.

- [x] 13. Frontend scaffolding
  - [x] 13.1 Create frontend directory structure and configuration files
    - Create `frontend/src/`, `frontend/public/`, `frontend/tests/` directories
    - Write `frontend/package.json` with `vitest`, `jsdom`, `typescript`, `vite` dev dependencies and `build` / `test` / `preview` scripts
    - Write `frontend/tsconfig.json` targeting ES2020 with strict mode enabled
    - Write `frontend/vite.config.ts` configuring `outDir: "dist"`, `envPrefix: "VITE_"`, and test environment `jsdom`
    - Update `.gitignore` to exclude `frontend/dist/`, `frontend/node_modules/`, `cdk.out/`, `**/__pycache__/`, `.venv/`
    - _Requirements: 8.11_

  - [x] 13.2 Write `frontend/public/index.html`
    - Implement HTML shell in `pt-BR` with `<h1>Em breve</h1>`, `<p class="intro">`, `.counter-card` section with `aria-labelledby="counter-label"`, `#counter-display` with `aria-live="polite"`, `#refresh-btn`, `#status-message` with `role="status" aria-live="assertive"`, and footer
    - _Requirements: 8.1, 8.7, 8.8_

  - [x] 13.3 Write `frontend/public/styles.css`
    - Implement CSS with `transition: opacity 0.3s ease` on `#counter-display`, `@media (prefers-reduced-motion: reduce)` disabling transitions, and `button:focus-visible` / `a:focus-visible` visible focus rings
    - _Requirements: 8.8_

- [x] 14. Frontend TypeScript implementation
  - [x] 14.1 Write `frontend/src/types.ts`
    - Define `Config { apiUrl: string }` and `CountResponse { count: number }` interfaces
    - _Requirements: 8.2_

  - [x] 14.2 Write `frontend/src/api.ts`
    - Implement `postHit(apiUrl: string): Promise<CountResponse>` using `fetch` with `method: "POST"`, `Content-Type: application/json`, and `AbortSignal.timeout(5000)`
    - Implement `getCount(apiUrl: string): Promise<CountResponse>` using `fetch` GET
    - Implement `mockFetch(): Promise<CountResponse>` returning `{ count: 42 }` for OAD mode
    - _Requirements: 8.3, 8.5, 8.10_

  - [x] 14.3 Write `frontend/src/main.ts`
    - Implement `loadConfig()` (reads `/config.json`; returns mock config in OAD mode)
    - Implement `formatCount(n)` using `Intl.NumberFormat("pt-BR")`
    - Implement `setLoading()`, `setCount()`, `setError()` DOM update functions with aria-live region updates
    - Implement `sendHit()` with `hitSent` guard (exactly one `POST /hit` per page load, no auto-retry on timeout)
    - Implement `refreshCount()` (calls `getCount`, never `postHit`)
    - Implement `init()` connecting `sendHit` on DOMContentLoaded and `refreshCount` on button click
    - Detect OAD mode via `VITE_OAD_MODE` env var or `?oad=1` URL param
    - _Requirements: 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.9, 8.10_

- [x] 15. CDK deploy integration (config.json generation and asset upload)
  - [x] 15.1 Add `config.json` generation and S3 sync to deploy script / `app.py`
    - After `cdk deploy`, generate `config.json` using the `ApiUrl` CloudFormation output
    - Document (in comments in `app.py` or a `deploy.sh` script) the sequence: `npm run build` → `cdk deploy` → `aws s3 sync frontend/dist/ s3://<bucket>/` → `aws s3 cp config.json s3://<bucket>/config.json` → `aws cloudfront create-invalidation --paths "/index.html" "/config.json"`
    - _Requirements: 2.7, 8.2_

- [x] 16. Frontend tests
  - [x] 16.1 Write `frontend/tests/setup.ts` for jsdom test environment
    - Configure global `fetch` mock and `window.location` stub for Vitest + jsdom
    - _Requirements: 11.4_

  - [x] 16.2 Write Vitest unit tests for frontend behaviour
    - In `frontend/tests/main.test.ts`, test: exactly one `POST /hit` sent on page load; `POST /hit` count stays 1 after multiple button clicks; refresh button triggers `GET /count` not `POST /hit`; loading state aria-live region updated while request in flight; error state displayed when `POST /hit` fails; error state displayed when `GET /count` fails; OAD mode makes zero real fetch calls
    - _Requirements: 11.4_

  - [x] 16.3 Write Vitest property tests for frontend
    - In `frontend/tests/main.test.ts`, add property tests for:
      - **Property 12**: Counter display equals `Intl.NumberFormat("pt-BR").format(n)` for any non-negative integer (validates Req 8.6)
      - **Property 13**: Exactly one `POST /hit` for any sequence of user interactions (validates Req 8.3, 8.4)
      - **Property 14**: Refresh button sends `GET /count` exactly `k` times and `POST /hit` exactly 1 time for any `k ≥ 1` (validates Req 8.5)
      - **Property 15**: All fetch calls use `apiUrl` from `config.json` as the base (validates Req 8.2)
    - _Requirements: 11.4_

- [x] 17. Checkpoint — Frontend tests pass
  - Run `cd frontend && npm run test -- --run`. Ask the user if any questions arise.

- [x] 18. Backend integration test (opt-in)
  - [x] 18.1 Write opt-in integration test in `tests/test_integration.py`
    - Skip unless `INTEGRATION_TEST=true` env var is set; also skip if `environment` context == `"production"`
    - Send N sequential `POST /hit` requests to the live API, then `GET /count`, assert counter increased by exactly N
    - _Requirements: 11.5_

- [x] 19. README and deployment documentation
  - [x] 19.1 Rewrite `README.md`
    - Document prerequisites: Python ≥ 3.12, Node.js ≥ 18, AWS CDK CLI v2, AWS CLI v2, required IAM permissions
    - Document CDK bootstrapping for both `us-east-1` (CertStack, custom domain only) and `us-east-2` (AppStack)
    - Document complete deployment sequence: install Python deps → build frontend (`npm run build`) → `cdk synth` → `cdk diff` → `cdk deploy` → S3 sync → `config.json` upload → CloudFront invalidation
    - Document DNS prerequisites for custom domain (pre-existing Route 53 public hosted zone)
    - Document main cost drivers: CloudFront data transfer, API Gateway requests, Lambda invocations, DynamoDB on-demand RCU/WCU, WAF Web ACL monthly fee
    - Document cleanup procedure and explicit warning that in `production` environment the DynamoDB table is RETAINED and must be deleted manually after `cdk destroy`
    - Include Mermaid architecture diagram from the design document
    - Note that CORS is browser-enforced and not a substitute for auth; note WAF false-positive risk and WAF log consultation
    - Note alarms do not auto-notify — document how to attach an SNS topic action
    - Note DynamoDB single-partition limitation and sharded counter recommendation for high throughput
    - Note AWS Shield Standard is automatic with CloudFront; Shield Advanced is NOT provisioned
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

- [x] 20. Final checkpoint — All tests pass
  - Run `pytest` (backend + infra tests) and `cd frontend && npm run test -- --run`. Confirm `cdk synth` produces no errors. Ask the user if any questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP delivery
- Every task references specific requirement IDs for traceability
- Property tests (tasks 3.3, 16.3) map to the Correctness Properties section of the design document
- The `CertStack` (task 9) is never instantiated in default deployments — it is guarded by the absence of `domain_name` context
- DynamoDB single-partition write throughput limitation is a known design constraint documented in requirements (3.10) and README (task 19.1)
- `frontend/dist/` is git-ignored; the build step is part of the deployment workflow, not the source repository
- Integration tests (task 18.1) MUST NOT be run against `environment=production`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "3.3", "5.1"] },
    { "id": 3, "tasks": ["5.2", "13.1"] },
    { "id": 4, "tasks": ["5.3", "6.1", "13.2", "13.3"] },
    { "id": 5, "tasks": ["6.2", "6.3", "7.1", "14.1"] },
    { "id": 6, "tasks": ["7.2", "8.1", "14.2"] },
    { "id": 7, "tasks": ["7.3", "8.2", "14.3"] },
    { "id": 8, "tasks": ["8.3", "9.1", "15.1"] },
    { "id": 9, "tasks": ["9.2", "10.1", "16.1"] },
    { "id": 10, "tasks": ["11.1", "16.2", "16.3"] },
    { "id": 11, "tasks": ["11.2", "18.1"] },
    { "id": 12, "tasks": ["19.1"] }
  ]
}
```

## Implementation amendments

The completed implementation uses an explicit certificate ARN handoff between regions; regional CloudFormation exports cannot implement this cross-region dependency. Incomplete domain configuration fails explicitly. `total_max_attempts=1` disables SDK write retries. CSP references the API ID/origin, never the stage URL, to avoid a dependency cycle. OPTIONS uses Lambda to select one allowed origin; gateway-generated errors allow the primary site only. Development origins are opt-in. Vite's entry is `frontend/index.html` and styles are bundled from `frontend/src/styles.css`. `deploy.sh` and `scripts/publish_frontend.py` own asset publication. DynamoDB alarms cover the two operations actually used, with an additional UpdateItem throttle alarm. See README and VERIFICATION.md for the authoritative implemented behavior and validation scope.

## Completion record

All implementation and local checkpoint tasks above are complete. Some unchecked tasks already had partial implementations; they were validated and corrected, not merely marked complete. Task 18 delivers an opt-in test; it has NOT been run against AWS. Browser rendering QA remains unverified because Chromium installation was blocked in this environment. No AWS deployment or live load test was performed. See VERIFICATION.md.
