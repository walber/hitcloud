# Requirements Document

## Introduction

A serverless page-view counter for a marketing "Coming Soon" page. Each page load calls a single HTTP endpoint that atomically increments a persistent counter and returns the updated total. The solution is provisioned entirely with AWS CDK in Python, requires no server management, and scales automatically to handle traffic between 10 and 1 million visits. Authentication, unique-visitor tracking, and analytics are explicitly out of scope.

## Glossary

- **Counter API**: The HTTP API exposed by Amazon API Gateway that receives page-view requests.
- **Hit Handler**: The AWS Lambda function that processes each request, increments the counter, and returns the updated total.
- **Counter Table**: The Amazon DynamoDB table that persists the visit count.
- **Counter Item**: The single DynamoDB item with partition key `id = "hits"` and numeric attribute `count`.
- **CDK Stack**: The AWS CDK Python application that provisions all infrastructure resources.
- **Browser Client**: The existing "Coming Soon" page that calls the Counter API once per page load.
- **CORS**: Cross-Origin Resource Sharing headers that allow the Browser Client to call the Counter API from any origin.

---

## Requirements

### Requirement 1: HTTP Endpoint

**User Story:** As a marketing team member, I want an HTTP endpoint that the "Coming Soon" page can call, so that each page load is registered as a visit.

#### Acceptance Criteria

1. THE Counter API SHALL expose a `POST /hits` endpoint accessible over HTTPS.
2. WHEN the Browser Client sends a `POST /hits` request, THE Counter API SHALL forward the request to the Hit Handler.
3. THE Counter API SHALL include a `Access-Control-Allow-Origin: *` response header on every response from the `POST /hits` route.
4. THE Counter API SHALL include a `Access-Control-Allow-Methods: POST, OPTIONS` response header on every response from the `POST /hits` route.
5. WHEN the Browser Client sends an HTTP `OPTIONS` preflight request to `/hits`, THE Counter API SHALL respond with HTTP status 200 and the appropriate CORS headers.

---

### Requirement 2: Counter Increment

**User Story:** As a marketing team member, I want every page load to increment the counter, so that repeat visits are all counted.

#### Acceptance Criteria

1. WHEN the Hit Handler receives an invocation from the Counter API, THE Hit Handler SHALL execute a DynamoDB `UpdateItem` operation using an atomic `ADD` expression on the `count` attribute of the Counter Item.
2. THE Hit Handler SHALL NOT perform a read-modify-write sequence; the increment MUST be a single atomic `UpdateItem` call.
3. WHEN the `UpdateItem` operation succeeds, THE Hit Handler SHALL return the updated value of the `count` attribute to the caller.
4. THE Hit Handler SHALL return a JSON response body in the format `{"count": <number>}` where `<number>` is the updated total.
5. THE Hit Handler SHALL return HTTP status 200 for every successful increment.
6. IF the DynamoDB `UpdateItem` operation fails (due to throttling, conditional failure, or service error), THEN THE Hit Handler SHALL return HTTP status 500 or 503 with a JSON error body and SHALL NOT include a `count` field in the response.

---

### Requirement 3: Counter Persistence

**User Story:** As a marketing team member, I want the visit count to survive between requests and deployments, so that the displayed total is always accurate.

#### Acceptance Criteria

1. THE Counter Table SHALL use `id` (String) as its sole partition key with no sort key.
2. THE Counter Table SHALL use on-demand (pay-per-request) billing mode.
3. IF the Counter Item with `id = "hits"` does not exist at deploy time, THEN THE CDK Stack SHALL create the Counter Item `{"id": "hits", "count": 0}` so that the first increment starts from zero; IF the Counter Item already exists, THE CDK Stack SHALL leave the existing item and its count untouched.
4. WHILE the Counter Table exists, THE Hit Handler SHALL read and write only the single Counter Item with `id = "hits"`.

---

### Requirement 4: Error Handling

**User Story:** As a developer, I want the API to return a clear error response when something goes wrong, so that the Browser Client can handle failures gracefully.

#### Acceptance Criteria

1. IF the Hit Handler encounters a DynamoDB service error, THEN THE Hit Handler SHALL return HTTP status 500 and a JSON body `{"error": "Internal server error"}`.
2. IF the Counter API receives a request on any route other than `POST /hits` or `OPTIONS /hits`, THEN THE Counter API SHALL return HTTP status 404.
3. THE Hit Handler SHALL emit a structured log entry to Amazon CloudWatch Logs for every invocation, including the resulting count or the error message.

---

### Requirement 5: IAM Least Privilege

**User Story:** As a security-conscious operator, I want each component to have only the permissions it needs, so that the blast radius of a misconfiguration is minimised.

#### Acceptance Criteria

1. THE CDK Stack SHALL grant the Hit Handler IAM permission `dynamodb:UpdateItem` scoped exclusively to the ARN of the Counter Table.
2. THE CDK Stack SHALL grant the Hit Handler IAM permission to write logs to Amazon CloudWatch Logs (`logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`).
3. THE CDK Stack SHALL NOT grant the Hit Handler any DynamoDB permissions beyond `dynamodb:UpdateItem`.
4. THE CDK Stack SHALL grant the Counter API IAM permission `lambda:InvokeFunction` scoped exclusively to the ARN of the Hit Handler.
5. THE CDK Stack SHALL NOT attach any AWS-managed policies broader than required to the Hit Handler execution role.

---

### Requirement 6: Infrastructure as Code

**User Story:** As a developer, I want all resources provisioned through CDK, so that the environment is reproducible and no manual console work is required.

#### Acceptance Criteria

1. THE CDK Stack SHALL provision the Counter Table, Hit Handler, and Counter API as a single deployable unit.
2. THE CDK Stack SHALL be written entirely in Python using the AWS CDK library.
3. WHEN `cdk deploy` is executed, THE CDK Stack SHALL create or update all resources without requiring any manual AWS Console steps.
4. WHEN `cdk destroy` is executed, THE CDK Stack SHALL remove all provisioned resources.
5. THE CDK Stack SHALL export the Counter API endpoint URL as a CloudFormation output named `HitsApiUrl`.

---

### Requirement 7: Browser Integration

**User Story:** As a web developer, I want a minimal browser snippet that calls the counter API and displays the result, so that I can integrate the counter into the existing page without rebuilding it.

#### Acceptance Criteria

1. THE CDK Stack documentation SHALL include a JavaScript `fetch` snippet that sends a `POST` request to the `HitsApiUrl` endpoint and reads the `count` field from the JSON response.
2. THE fetch snippet SHALL update a DOM element with the returned count value.
3. THE fetch snippet SHALL handle a failed request without throwing an uncaught exception.
4. WHERE the existing page already includes the `HitsApiUrl` value, THE fetch snippet SHALL require no server-side changes to the existing page.

---

### Requirement 8: Scalability

**User Story:** As a marketing team member, I want the solution to handle unpredictable traffic spikes automatically, so that the counter keeps working if the campaign goes viral.

#### Acceptance Criteria

1. THE Counter API SHALL use a serverless compute model with no pre-provisioned server capacity.
2. THE Counter Table SHALL use on-demand capacity scaling so that read and write throughput adjusts automatically to the request rate.
3. THE CDK Stack documentation SHALL state the known AWS service limits that apply to the solution (Lambda concurrency, DynamoDB on-demand throughput, API Gateway requests per second).
