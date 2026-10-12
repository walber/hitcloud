# Requirements Document

## Introduction

This feature migrates and expands the existing HitCloud serverless page-view counter into a production-ready, deployable website. The system consists of a static "Em breve" (Coming Soon) page hosted on S3 + CloudFront, a REST API backed by API Gateway (v1) + Lambda + DynamoDB for atomic counter operations, WAFv2 protection, optional Route 53 custom domain, CloudWatch observability, and a complete Infrastructure-as-Code definition using AWS CDK v2 (Python). The implementation scope is limited to the shared page-access counter; email registration, SQS, SES, authentication, and subscriber management are explicitly excluded.

---

## Glossary

- **CDK App**: The AWS CDK v2 Python application (`app.py`) that synthesises one or more CloudFormation stacks.
- **AppStack**: The primary CDK stack deployed to `us-east-2` that contains S3, CloudFront, API Gateway, Lambda, DynamoDB, WAFv2, and CloudWatch resources.
- **CertStack**: An optional CDK stack deployed to `us-east-1` that provisions an ACM certificate for a custom domain and is referenced by AppStack via an explicit two-phase deployment output/ARN handoff.
- **Counter Table**: The DynamoDB table with partition key `id` (String), containing the single counter item `id="hits"`.
- **Hit Handler**: The AWS Lambda function (Python 3.12) that processes `POST /hit` and `GET /count` requests.
- **Frontend**: The static website consisting of HTML, CSS, and compiled TypeScript served from the S3 bucket via CloudFront.
- **Runtime Config**: A deployment-generated JSON file (`config.json`) placed in the S3 bucket that carries the API URL; consumed by the Frontend at runtime.
- **OAC**: CloudFront Origin Access Control — the mechanism that allows CloudFront to sign requests to the private S3 bucket.
- **WAF Web ACL**: The regional WAFv2 Web Access Control List associated with the API Gateway stage.
- **CORS**: Cross-Origin Resource Sharing — the HTTP mechanism that permits the Frontend origin to call the API from a browser.
- **CDK Context**: Key-value pairs passed to the CDK App via `cdk.json` or `-c` flags that configure optional behaviour such as custom domain, hosted zone, and environment names.
- **Managed Rules**: AWS Managed Rule Groups added to the WAF Web ACL (e.g., `AWSManagedRulesCommonRuleSet`).
- **PITR**: DynamoDB Point-In-Time Recovery — a continuous backup feature.
- **OAD Mode**: Local offline/mock mode for frontend development that bypasses the real API.

---

## Requirements

### Requirement 1 — Infrastructure Scope and Configuration

**User Story:** As a DevOps engineer, I want all infrastructure defined as CDK v2 Python code with configurable values, so that the system can be deployed reproducibly across environments without hard-coded identifiers or credentials.

#### Acceptance Criteria

1. THE CDK App SHALL define all AWS resources using `aws-cdk-lib==2.261.0` and `constructs>=10.0.0` with no manual console steps required for deployment.
2. THE CDK App SHALL read AWS account ID, region, environment name, domain name, hosted zone ID, and resource name prefixes exclusively from CDK context keys or environment variables; THE CDK App SHALL NOT contain hard-coded account identifiers or AWS credentials.
3. WHEN the CDK context key `domain_name` is absent, THE AppStack SHALL default the website hostname to the CloudFront distribution domain (`*.cloudfront.net`).
4. WHEN the CDK context key `domain_name` is present and `hosted_zone_id` is also present, THE AppStack SHALL associate the custom domain with the CloudFront distribution and reference an ACM certificate provisioned by CertStack.
5. THE CDK App SHALL produce reproducible infrastructure by tagging all resources with at minimum an `Environment` tag derived from CDK context.
6. THE CDK App SHALL output the following CloudFormation outputs: website URL, API invoke URL, CloudFront distribution ID, and DynamoDB table name.
7. THE CDK App SHALL provide a documented example CDK context file (no secrets) that demonstrates all configurable options.

---

### Requirement 2 — Static Website Hosting

**User Story:** As a visitor, I want to access a fast, secure "Em breve" page over HTTPS, so that the campaign launches reliably regardless of traffic volume.

#### Acceptance Criteria

1. THE AppStack SHALL provision a private S3 bucket with Block Public Access enabled, server-side encryption at rest (SSE-S3 or SSE-KMS), and versioning enabled for static asset management.
2. THE AppStack SHALL configure a CloudFront Origin Access Control (OAC) with request signing set to `always`; THE S3 bucket policy SHALL restrict `s3:GetObject` to the CloudFront distribution principal only.
3. THE AppStack SHALL configure the CloudFront distribution to redirect HTTP to HTTPS and to serve the S3 bucket as the origin using the OAC.
4. WHERE the CDK context key `domain_name` is present, THE AppStack SHALL attach the ACM certificate (provisioned in `us-east-1`) to the CloudFront distribution and add the custom domain as an alternate name.
5. THE AppStack SHALL configure CloudFront cache behaviours so that HTML and `config.json` are cached with a short TTL (maximum 60 seconds) and versioned static assets (JS, CSS with content-hash filenames) are cached with a long TTL (minimum 1 year).
6. THE AppStack SHALL configure CloudFront to add browser security response headers including `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and a `Content-Security-Policy` that allows only the configured API endpoint as a `connect-src`.
7. THE AppStack SHALL perform a targeted CloudFront invalidation of `/index.html` and `/config.json` after each frontend deployment.
8. THE AppStack SHALL document that AWS Shield Standard is automatically included with CloudFront at no additional cost and SHALL NOT provision AWS Shield Advanced.

---

### Requirement 3 — REST API

**User Story:** As the Frontend, I want a REST API that atomically increments and reliably reads a shared counter, so that page-access counts are accurate under concurrent load.

#### Acceptance Criteria

1. THE AppStack SHALL provision an API Gateway REST API (v1) deployed to a stage named after the environment, with `application/json` as the default content type and no API-level response caching.
2. THE AppStack SHALL configure the API Gateway stage with throttling: a configurable burst limit (default 500 requests) and a configurable rate limit (default 1000 requests per second).
3. THE AppStack SHALL associate the WAF Web ACL with the API Gateway stage ARN.
4. WHEN a `POST /hit` request is received, THE Hit Handler SHALL execute a DynamoDB `UpdateItem` with expression `SET #count = if_not_exists(#count, :zero) + :one`, `ReturnValues=ALL_NEW`, and SHALL return HTTP 200 with `Content-Type: application/json` and body `{"count": <number>}`; THE Hit Handler SHALL NOT perform a read-modify-write sequence for the increment.
5. THE Hit Handler SHALL initialise the boto3 DynamoDB client for `POST /hit` with `total_max_attempts=1` (retry disabled) to prevent double-increments from retry logic on non-idempotent operations.
6. WHEN a `GET /count` request is received, THE Hit Handler SHALL perform a strongly consistent `GetItem` with key `{"id": "hits"}` and SHALL return HTTP 200 with `Content-Type: application/json` and body `{"count": <number>}`; WHEN the item is absent, THE Hit Handler SHALL return `{"count": 0}`.
7. THE Hit Handler SHALL NOT modify the counter value during a `GET /count` operation.
8. WHEN a DynamoDB `ProvisionedThroughputExceededException` or transient service error is received, THE Hit Handler SHALL return HTTP 503 with body `{"error": "Service temporarily unavailable"}` and SHALL log the error type without logging request bodies or credentials.
9. WHEN an unrecognised HTTP method or path is received by the Hit Handler, THE Hit Handler SHALL return HTTP 405 with body `{"error": "Method not allowed"}`.
10. THE AppStack documentation SHALL note that DynamoDB on-demand capacity handles bursts automatically but that a single partition key `id="hits"` is subject to the per-partition write throughput limit and SHALL recommend a sharded counter design for sustained high-throughput scenarios.

---

### Requirement 4 — CORS

**User Story:** As the Frontend loaded in a browser, I want CORS headers returned on all API responses, so that browsers permit cross-origin fetch requests to the counter API.

#### Acceptance Criteria

1. THE AppStack SHALL configure API Gateway to handle `OPTIONS` preflight requests for `/hit` and `/count` and SHALL return `Access-Control-Allow-Origin`, `Access-Control-Allow-Methods`, and `Access-Control-Allow-Headers` headers.
2. THE Hit Handler SHALL include `Access-Control-Allow-Origin` restricted to the deployed CloudFront origin (or custom domain) in every response, including error responses; THE Hit Handler SHALL also include explicitly configured development origins when the environment is not production.
3. IF an API Gateway error occurs before the Hit Handler is invoked (e.g., WAF block, throttle), THEN THE AppStack SHALL configure API Gateway gateway responses to include CORS headers.
4. THE deployment documentation SHALL state that CORS is a browser-enforced mechanism and is not a substitute for authentication or authorisation.

---

### Requirement 5 — DynamoDB Counter Table

**User Story:** As a system operator, I want the counter data stored durably with production-safe retention settings, so that access counts survive failures and accidental deployments.

#### Acceptance Criteria

1. THE AppStack SHALL provision the Counter Table with partition key `id` (String), on-demand billing mode, encryption at rest using AWS-managed keys, and Point-In-Time Recovery (PITR) enabled.
2. WHILE the environment is `production`, THE AppStack SHALL set the Counter Table removal policy to `RETAIN` and SHALL enable deletion protection.
3. WHILE the environment is NOT `production`, THE AppStack SHALL allow the Counter Table removal policy to be `DESTROY` and SHALL disable deletion protection, to support clean teardown in non-production environments.
4. THE AppStack SHALL NOT seed the counter item via a CDK custom resource; THE Hit Handler's `if_not_exists` expression SHALL handle first-write initialisation without a pre-seeded item.

---

### Requirement 6 — Lambda Hit Handler

**User Story:** As a developer, I want the Lambda function to have least-privilege IAM permissions, structured logging, and safe error handling, so that the function is secure, observable, and resilient.

#### Acceptance Criteria

1. THE AppStack SHALL grant the Hit Handler IAM permissions for only `dynamodb:UpdateItem` (for `POST /hit`) and `dynamodb:GetItem` (for `GET /count`) on the Counter Table ARN; THE AppStack SHALL NOT grant broader permissions such as `dynamodb:*` or full read/write data grants.
2. THE AppStack SHALL grant the Hit Handler IAM permissions for `logs:CreateLogGroup`, `logs:CreateLogStream`, and `logs:PutLogEvents` scoped to the function's own log group.
3. THE AppStack SHALL configure the Hit Handler log group with a configurable retention period (default 30 days).
4. THE Hit Handler SHALL emit exactly one structured JSON log entry per invocation containing at minimum a `status` field (`"ok"` or `"error"`) and SHALL NOT log request bodies, HTTP headers, or any PII.
5. THE Hit Handler SHALL set the `Cache-Control: no-store` response header on all responses to prevent client-side and proxy caching of counter values.
6. THE AppStack SHALL configure the API Gateway resource policy or Lambda resource policy to restrict invocation to the specific API Gateway ARN, preventing direct Lambda invocations from other sources.

---

### Requirement 7 — WAFv2 Web ACL

**User Story:** As a security engineer, I want a WAFv2 Web ACL protecting the API, so that common web attacks and abusive traffic patterns are blocked before reaching Lambda.

#### Acceptance Criteria

1. THE AppStack SHALL provision a regional WAFv2 Web ACL and associate it with the API Gateway stage.
2. THE AppStack SHALL attach at minimum the `AWSManagedRulesCommonRuleSet` managed rule group to the WAF Web ACL with a configurable override action.
3. THE AppStack SHALL configure a rate-based rule on the WAF Web ACL with a configurable request threshold (default 1000 requests per 5-minute window) per source IP.
4. THE AppStack documentation SHALL state that WAF managed rules may produce false positives, that the WAF blocks requests before they reach Lambda and therefore the Lambda error metrics will not reflect WAF-blocked requests, and that WAF logs should be consulted for complete traffic analysis.

---

### Requirement 8 — Frontend Web Page

**User Story:** As a visitor, I want an accessible "Em breve" page in Brazilian Portuguese that displays the live access count, so that I can see community interest in the campaign.

#### Acceptance Criteria

1. THE Frontend SHALL display a heading "Em breve", a configurable introductory sentence, a counter card labelled "Total de acessos", an "Atualizar contagem" button, and a footer section.
2. THE Frontend SHALL load the API URL exclusively from the deployment-generated `config.json` file and SHALL NOT contain hard-coded API URLs or AWS credentials.
3. WHEN the page finishes loading, THE Frontend SHALL send exactly one `POST /hit` request and SHALL display the `count` value returned in the response.
4. THE Frontend SHALL NOT send more than one `POST /hit` request per page load regardless of subsequent user interactions or network retries.
5. WHEN the "Atualizar contagem" button is activated, THE Frontend SHALL send a `GET /count` request and SHALL update the displayed count with the returned value; THE Frontend SHALL NOT send a `POST /hit` on button activation.
6. THE Frontend SHALL format all displayed counter values using `Intl.NumberFormat("pt-BR")` and SHALL NOT use `localStorage`, cookies, or hard-coded fallback values for the counter display.
7. THE Frontend SHALL display a loading state (with an `aria-live` region) while an API request is in progress, a success state showing the count, and an error state with a user-visible message in Brazilian Portuguese when the API call fails.
8. THE Frontend SHALL support keyboard navigation with visible focus indicators on all interactive elements and SHALL respect the `prefers-reduced-motion` media query for any animations.
9. WHEN the page is loaded in local development mode (OAD Mode), THE Frontend SHALL use a local mock API response and SHALL NOT make real network requests to AWS.
10. IF a `POST /hit` request times out, THEN THE Frontend SHALL display the error state and SHALL NOT automatically retry the request.
11. THE Frontend source SHALL be written in TypeScript, compiled to JavaScript before deployment, and SHALL NOT include the TypeScript compiler output in the source repository.

---

### Requirement 9 — ACM Certificate (Optional, us-east-1)

**User Story:** As a domain owner, I want an ACM certificate provisioned automatically when I configure a custom domain, so that HTTPS works with my domain without manual certificate management.

#### Acceptance Criteria

1. WHERE the CDK context key `domain_name` is present AND the CDK context key `hosted_zone_id` is also present, THE CertStack SHALL provision an ACM certificate in the `us-east-1` region using DNS validation against the Route 53 hosted zone identified by the `hosted_zone_id` context key; WHEN only one of `domain_name` and `hosted_zone_id` is supplied, synthesis SHALL fail with a configuration error to prevent silently ignoring an intended custom domain.
2. WHERE the CDK context key `domain_name` is present, THE AppStack SHALL reference the CertStack certificate ARN via an explicit two-phase deployment output/ARN handoff and SHALL NOT re-provision the certificate in `us-east-2`.
3. WHERE the CDK context key `domain_name` is absent, THE CertStack SHALL NOT be instantiated and the AppStack SHALL NOT require a certificate ARN.

---

### Requirement 10 — CloudWatch Observability

**User Story:** As an operator, I want CloudWatch alarms for Lambda errors, API 5xx responses, and DynamoDB throttling, so that I am notified when the system degrades.

#### Acceptance Criteria

1. THE AppStack SHALL create a CloudWatch alarm on the Hit Handler's `Errors` metric with a configurable threshold (default: 1 error in 1 minute) that transitions to ALARM state when the threshold is breached.
2. THE AppStack SHALL create a CloudWatch alarm on the Hit Handler's `Throttles` metric with a configurable threshold (default: 1 throttle in 1 minute).
3. THE AppStack SHALL create a CloudWatch alarm on the API Gateway `5XXError` metric for the deployed stage with a configurable threshold (default: 5 errors in 1 minute).
4. THE AppStack SHALL create a CloudWatch alarm on the Counter Table's `SystemErrors` metric with a configurable threshold (default: 1 error in 1 minute).
5. THE AppStack documentation SHALL explain that alarms transition to ALARM state but do not automatically send notifications unless an SNS topic or other action is configured, and SHALL provide instructions for attaching an SNS alarm action.

---

### Requirement 11 — Automated Tests

**User Story:** As a developer, I want a comprehensive automated test suite covering backend behaviour, infrastructure properties, and frontend behaviour, so that regressions are caught before deployment.

#### Acceptance Criteria

1. THE test suite SHALL include pytest-based unit tests for the Hit Handler that verify: `GET /count` returns `{"count": 0}` when no item exists in DynamoDB; `GET /count` does not call `UpdateItem` or modify the counter; `POST /hit` calls `UpdateItem` with the atomic expression and returns the updated count; concurrent `POST /hit` invocations do not lose increments (verified via mocked atomic semantics); and backend DynamoDB failures return `{"error": "..."}` with a 5xx status.
2. THE test suite SHALL include Hypothesis property-based tests for the Hit Handler covering at minimum: CORS headers present on all response paths; correct `count` value reflected in the response body for any integer count; counter item key is always `{"id": "hits"}`; and any exception from DynamoDB produces an HTTP 5xx response.
3. THE test suite SHALL include `aws_cdk.assertions`-based infrastructure tests (Python, pytest) that verify: the S3 bucket has Block Public Access enabled; the CloudFront distribution uses OAC (not OAI); the Hit Handler IAM role grants only `dynamodb:UpdateItem` and `dynamodb:GetItem` (no broader permissions); the WAF Web ACL is associated with the API Gateway stage; and the Counter Table has PITR enabled.
4. THE test suite SHALL include TypeScript/Jest or Vitest tests for the Frontend that verify: exactly one `POST /hit` is sent on page load; the refresh button sends `GET /count` and never `POST /hit`; the loading state is displayed while a request is in progress; and the error state is displayed when the API call fails.
5. WHERE the CDK context key `integration_test` is set to `true`, THE test suite SHALL include an opt-in integration test that sends N `POST /hit` requests sequentially, reads the counter with `GET /count`, and asserts the counter increased by at least N (allowing for tolerance due to concurrent external traffic); the test SHALL implement a configurable tolerance margin and MAY retry the count assertion up to a configurable number of times before failing; this test SHALL be excluded from default CI runs and SHALL NOT be run against production.
6. THE test suite SHALL include visual regression or rendering checks that verify the page renders correctly at both mobile (375 px viewport) and desktop (1280 px viewport) breakpoints.

---

### Requirement 12 — Deployment Documentation

**User Story:** As a new engineer, I want complete, accurate deployment documentation, so that I can set up the environment and deploy the stack from scratch without prior context.

#### Acceptance Criteria

1. THE README SHALL document all prerequisites including AWS CLI version, Node.js version, AWS CDK CLI version, Python version, and required AWS IAM permissions.
2. THE README SHALL document the CDK bootstrapping command, including the need to bootstrap both `us-east-1` (for CertStack) and `us-east-2` (for AppStack) when a custom domain is configured.
3. THE README SHALL document the complete deployment command sequence: install Python dependencies, build and compile the frontend TypeScript, synthesise the CDK app, diff against the deployed stack, and deploy.
4. THE README SHALL document the DNS prerequisites required when a custom domain is configured, including the need for a pre-existing Route 53 public hosted zone.
5. THE README SHALL document the main cost drivers: CloudFront data transfer, API Gateway requests, Lambda invocations, DynamoDB on-demand read/write units, and WAF Web ACL monthly fee.
6. THE README SHALL document the cleanup procedure (`cdk destroy`) and SHALL explicitly warn that in production environments the DynamoDB table is retained (due to `RETAIN` removal policy) and must be deleted manually to avoid ongoing storage costs.
7. THE README SHALL include a Mermaid architecture diagram showing the flow: Browser → Route 53 (optional) → CloudFront → S3 (static assets) and Browser → WAF → API Gateway → Lambda → DynamoDB, with CloudWatch monitoring all compute and data components.

## Implementation amendments

The completed implementation uses an explicit certificate ARN handoff between regions; regional CloudFormation exports cannot implement this cross-region dependency. Incomplete domain configuration fails explicitly. `total_max_attempts=1` disables SDK write retries. CSP references the API ID/origin, never the stage URL, to avoid a dependency cycle. OPTIONS uses Lambda to select one allowed origin; gateway-generated errors allow the primary site only. Development origins are opt-in. Vite's entry is `frontend/index.html` and styles are bundled from `frontend/src/styles.css`. `deploy.sh` and `scripts/publish_frontend.py` own asset publication. DynamoDB alarms cover the two operations actually used, with an additional UpdateItem throttle alarm. See README and VERIFICATION.md for the authoritative implemented behavior and validation scope.
