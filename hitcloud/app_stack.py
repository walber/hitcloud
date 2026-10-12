import aws_cdk as cdk
from aws_cdk import Duration, Stack
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
import json
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# RetentionDays only accepts predefined enum members; raw integers are not
# valid. Map the common integer day values from cdk.json context to the
# nearest supported enum member.
_RETENTION_MAP: dict[int, logs.RetentionDays] = {
    1: logs.RetentionDays.ONE_DAY,
    3: logs.RetentionDays.THREE_DAYS,
    5: logs.RetentionDays.FIVE_DAYS,
    7: logs.RetentionDays.ONE_WEEK,
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
    60: logs.RetentionDays.TWO_MONTHS,
    90: logs.RetentionDays.THREE_MONTHS,
    120: logs.RetentionDays.FOUR_MONTHS,
    150: logs.RetentionDays.FIVE_MONTHS,
    180: logs.RetentionDays.SIX_MONTHS,
    365: logs.RetentionDays.ONE_YEAR,
    400: logs.RetentionDays.THIRTEEN_MONTHS,
    545: logs.RetentionDays.EIGHTEEN_MONTHS,
    731: logs.RetentionDays.TWO_YEARS,
    1096: logs.RetentionDays.THREE_YEARS,
    1827: logs.RetentionDays.FIVE_YEARS,
    2192: logs.RetentionDays.SIX_YEARS,
    2557: logs.RetentionDays.SEVEN_YEARS,
    2922: logs.RetentionDays.EIGHT_YEARS,
    3288: logs.RetentionDays.NINE_YEARS,
    3653: logs.RetentionDays.TEN_YEARS,
    0: logs.RetentionDays.INFINITE,
}


def _retention_days(days: int) -> logs.RetentionDays:
    """Convert an integer number of days to a ``logs.RetentionDays`` enum member.

    Falls back to ``ONE_MONTH`` when the value is not in the supported set.
    """
    return _RETENTION_MAP.get(days, logs.RetentionDays.ONE_MONTH)


# ---------------------------------------------------------------------------
# Stack
# ---------------------------------------------------------------------------


class AppStack(Stack):
    """Regional counter backend and global website delivery resources."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        certificate: "acm.ICertificate | None" = None,
        certificate_arn: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if certificate_arn:
            certificate = acm.Certificate.from_certificate_arn(self, "ImportedCertificate", certificate_arn)

        # ── Context / environment ─────────────────────────────────────────────
        env = self.node.try_get_context("environment") or "dev"
        is_production = env == "production"
        log_retention_days = int(
            self.node.try_get_context("log_retention_days") or 30
        )
        api_burst_limit = int(
            self.node.try_get_context("api_burst_limit") or 500
        )
        api_rate_limit = int(
            self.node.try_get_context("api_rate_limit") or 1000
        )
        waf_rate_limit = int(
            self.node.try_get_context("waf_rate_limit") or 1000
        )
        # Conservative application minimum for the configured rate rule.
        waf_rate_limit = max(100, waf_rate_limit)

        # ── 1. DynamoDB Counter Table (Task 2.1) ──────────────────────────────
        # Partition key: id (String)
        # On-demand billing, AWS-managed encryption, PITR enabled.
        # Production: RETAIN removal policy + deletion protection enabled.
        # Non-production: DESTROY removal policy, deletion protection disabled.
        self.table = dynamodb.Table(
            self,
            "CounterTable",
            partition_key=dynamodb.Attribute(
                name="id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
            deletion_protection=is_production,
            removal_policy=(
                cdk.RemovalPolicy.RETAIN
                if is_production
                else cdk.RemovalPolicy.DESTROY
            ),
        )

        # ── 2. CloudWatch Log Group (Task 5.1) ────────────────────────────────
        # Scoped log group created before the Lambda function so the ARN is
        # available for the least-privilege log policy added in task 5.2.
        # Retention is driven by the log_retention_days context key (default 30).
        self.log_group = logs.LogGroup(
            self,
            "HitHandlerLogGroup",
            log_group_name=f"/aws/lambda/HitHandler-{env}",
            retention=_retention_days(log_retention_days),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # ── 3. Lambda Hit Handler (Task 5.1) ──────────────────────────────────
        # Runtime: Python 3.12.  Handler: handler.handler in lambda/handler.py.
        # ALLOWED_ORIGIN starts as "*"; overridden with the real CloudFront URL
        # via add_environment() after the distribution is created below.
        handler_role = iam.Role(self, "HandlerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        self.hit_handler = _lambda.Function(
            self,
            "HitHandler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            role=handler_role,
            timeout=Duration.seconds(5),
            handler="handler.handler",
            code=_lambda.Code.from_asset("lambda", exclude=["__pycache__", "*.pyc"]),
            environment={
                "TABLE_NAME": self.table.table_name,
                "ALLOWED_ORIGIN": "*",
            },
            log_group=self.log_group,
        )

        # ── 4a. IAM: least-privilege DynamoDB permissions (Task 5.2) ──────────
        # Grants only the two operations actually used by the Hit Handler.
        # Req 6.1: do NOT use dynamodb:* or grant_read_write_data.
        self.table.grant(
            self.hit_handler,
            "dynamodb:UpdateItem",
            "dynamodb:GetItem",
        )

        # ── 4b. IAM: least-privilege CloudWatch Logs permissions (Task 5.2) ───
        # Req 6.2: scoped to the function's own log group ARN and its streams.
        # The Lambda execution role receives these log permissions explicitly
        # rather than relying on the CDK-managed AWSLambdaBasicExecutionRole,
        # so we can scope them precisely to our pre-created log group.
        log_group_arn = self.log_group.log_group_arn
        self.hit_handler.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    log_group_arn,
                    f"{log_group_arn}:*",
                ],
            )
        )

        # ── 5. S3 Website Bucket (Task 8.1) ───────────────────────────────────
        # Req 2.1: private bucket with Block Public Access, SSE-S3 encryption,
        # versioning, and SSL enforcement.  Removal policy is always RETAIN so
        # static assets are never destroyed accidentally.
        self.website_bucket = s3.Bucket(
            self,
            "WebsiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            enforce_ssl=True,
        )

        # ── 6. CloudFront OAC + Distribution (Task 8.2) ───────────────────────
        # Placed BEFORE API Gateway so that distribution.domain_name is
        # available as a real CloudFormation token when constructing CORS
        # origins (step 7).  The CSP in the security-headers policy also needs
        # the API ID, but self.api is created in step 7 so we use a
        # CloudFormation escape-hatch override (add_override) to inject the
        # final CSP string after both constructs exist.

        # Req 2.2: OAC with SIGV4_ALWAYS signing.
        oac = cloudfront.S3OriginAccessControl(
            self,
            "OAC",
            signing=cloudfront.Signing.SIGV4_ALWAYS,
        )

        # Req 2.3: CloudFront served origin via OAC.
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(
            self.website_bucket,
            origin_access_control=oac,
        )

        # Req 2.5: short TTL (60 s) for HTML / config.json.
        short_ttl_policy = cloudfront.CachePolicy(
            self,
            "ShortTtl",
            default_ttl=Duration.seconds(60),
            max_ttl=Duration.seconds(60),
            min_ttl=Duration.seconds(0),
        )

        # Req 2.5: long TTL (365 d) for versioned JS/CSS assets.
        long_ttl_policy = cloudfront.CachePolicy(
            self,
            "LongTtl",
            default_ttl=Duration.days(365),
            max_ttl=Duration.days(365),
            min_ttl=Duration.days(365),
        )

        # Req 2.6: Security response-headers policy.
        # The CSP connect-src needs the API ID which is not created yet.
        # We create the policy WITHOUT a CSP here, then inject the CSP value
        # via a low-level CloudFormation add_override() after self.api exists.
        # All other security headers are fully specified now.
        security_headers_policy = cloudfront.ResponseHeadersPolicy(
            self,
            "SecurityHeaders",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.seconds(63072000),
                    include_subdomains=True,
                    override=True,
                ),
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(
                    override=True,
                ),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY,
                    override=True,
                ),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
                    override=True,
                ),
            ),
        )

        # Req 2.3: HTTP → HTTPS redirect.  Req 2.4: custom domain + cert.
        # Req 2.5: additional behaviours per path pattern.
        domain_name_ctx = self.node.try_get_context("domain_name")

        distribution_kwargs: dict = {}
        if certificate is not None and domain_name_ctx:
            distribution_kwargs["certificate"] = certificate
            distribution_kwargs["domain_names"] = [domain_name_ctx]

        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=s3_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=short_ttl_policy,
                response_headers_policy=security_headers_policy,
            ),
            additional_behaviors={
                "assets/*": cloudfront.BehaviorOptions(
                    origin=s3_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=long_ttl_policy,
                    response_headers_policy=security_headers_policy,
                ),
                "/config.json": cloudfront.BehaviorOptions(
                    origin=s3_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=short_ttl_policy,
                    response_headers_policy=security_headers_policy,
                ),
            },
            default_root_object="index.html",
            **distribution_kwargs,
        )

        # website_url is the real CloudFront domain (CF token) — used for CORS
        # origins and gateway response headers in step 7 and 9.
        website_url = f"https://{domain_name_ctx if certificate else self.distribution.domain_name}"

        # ── 7. API Gateway REST API v1 (Task 6.1) ─────────────────────────────
        # Req 3.1: REST API deployed to a stage named after the environment.
        # Req 3.2: Throttling: configurable burst/rate limits from context.
        # Req 4.1: CORS preflight handled by API Gateway for /hit and /count.
        # OPTIONS is wired below to the Lambda allowlist handler.
        self.api = apigw.RestApi(
            self,
            "CounterApi",
            rest_api_name=f"hitcloud-api-{env}",
            endpoint_types=[apigw.EndpointType.REGIONAL],
            deploy_options=apigw.StageOptions(
                stage_name=env,
                throttling_burst_limit=api_burst_limit,
                throttling_rate_limit=api_rate_limit,
                logging_level=apigw.MethodLoggingLevel.ERROR,
                data_trace_enabled=False,   # no PII in logs
                metrics_enabled=True,
            ),
            cloud_watch_role=True,
        )

        # Lambda integration with proxy=True so the handler controls the full
        # response including status code, headers, and body.
        lambda_integration = apigw.LambdaIntegration(
            self.hit_handler,
            proxy=True,
            allow_test_invoke=False,
        )

        # POST /hit — atomic counter increment
        hit_resource = self.api.root.add_resource("hit")
        hit_resource.add_method("POST", lambda_integration)

        # GET /count — strongly consistent counter read
        count_resource = self.api.root.add_resource("count")
        count_resource.add_method("GET", lambda_integration)

        # Use the API ID (not api.url/stage) in CSP to avoid a dependency cycle.
        # RestApi -> headers -> distribution -> Lambda -> methods -> stage.
        api_origin = f"https://{self.api.rest_api_id}.execute-api.{self.region}.{self.url_suffix}"
        security_headers_policy.node.default_child.add_property_override(
            "ResponseHeadersPolicyConfig.SecurityHeadersConfig.ContentSecurityPolicy",
            {"ContentSecurityPolicy": "default-src 'self'; script-src 'self'; style-src 'self'; "
             f"connect-src 'self' {api_origin}; img-src 'self' data:; "
             "object-src 'none'; base-uri 'self'; frame-ancestors 'none'", "Override": True})
        development_origins = self.node.try_get_context("development_origins") or []
        if not isinstance(development_origins, list) or any(
            not isinstance(origin, str) or origin == "*" for origin in development_origins
        ):
            raise ValueError("development_origins must be an explicit list of origins")
        self.hit_handler.add_environment("ALLOWED_ORIGIN", website_url)
        self.hit_handler.add_environment("EXTRA_ALLOWED_ORIGINS", json.dumps(development_origins))
        # Lambda selects one allowed origin, instead of an invalid comma-separated header.
        hit_resource.add_method("OPTIONS", lambda_integration)
        count_resource.add_method("OPTIONS", lambda_integration)

        if certificate and domain_name_ctx:
            zone = route53.HostedZone.from_hosted_zone_attributes(
                self, "WebsiteZone",
                hosted_zone_id=self.node.try_get_context("hosted_zone_id"),
                zone_name=self.node.try_get_context("hosted_zone_name") or domain_name_ctx)
            for record_class, suffix in [(route53.ARecord, "A"), (route53.AaaaRecord, "AAAA")]:
                record_class(self, f"Website{suffix}", zone=zone,
                    record_name=domain_name_ctx,
                    target=route53.RecordTarget.from_alias(targets.CloudFrontTarget(self.distribution)))

        # ── 8. WAFv2 Web ACL (Task 7.1) ───────────────────────────────────────
        # Req 7.1: Regional Web ACL associated with the API Gateway stage.
        # Req 7.2: AWSManagedRulesCommonRuleSet at priority 1.
        # Req 7.3: Rate-based block rule per IP at priority 2 with configurable
        #          threshold (waf_rate_limit context key, default 1000, min 100).
        self.web_acl = wafv2.CfnWebACL(
            self,
            "WebAcl",
            scope="REGIONAL",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name="HitCloudWebAcl",
                sampled_requests_enabled=True,
            ),
            rules=[
                # Rule 1 — AWS Managed Common Rule Set (priority 1)
                # override_action=none means the rule group's own actions apply.
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesCommonRuleSet",
                    priority=1,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name="AWSManagedRulesCommonRuleSet",
                        ),
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="AWSManagedRulesCommonRuleSet",
                        sampled_requests_enabled=True,
                    ),
                ),
                # Rule 2 — Rate-based block rule per IP (priority 2)
                # Blocks IPs that exceed waf_rate_limit requests per 5 minutes.
                wafv2.CfnWebACL.RuleProperty(
                    name="RateLimitPerIp",
                    priority=2,
                    action=wafv2.CfnWebACL.RuleActionProperty(
                        block=wafv2.CfnWebACL.BlockActionProperty(),
                    ),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            aggregate_key_type="IP",
                            limit=waf_rate_limit,
                        ),
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="RateLimitPerIp",
                        sampled_requests_enabled=True,
                    ),
                ),
            ],
        )

        # WAFv2 Web ACL Association (Task 7.2)
        # Req 3.3 + 7.1: Associate the Web ACL with the API Gateway stage ARN.
        stage_arn = (
            f"arn:{self.partition}:apigateway:{self.region}::"
            f"/restapis/{self.api.rest_api_id}/stages/{env}"
        )

        self.waf_association = wafv2.CfnWebACLAssociation(
            self,
            "WebAclAssociation",
            resource_arn=stage_arn,
            web_acl_arn=self.web_acl.attr_arn,
        )

        self.waf_association.node.add_dependency(self.api.deployment_stage)

        # ── 9. API Gateway gateway responses with CORS headers (Task 6.2) ─────
        # Req 4.3: when API Gateway rejects a request before reaching Lambda
        # (e.g. throttling, WAF block, missing auth), the error response must
        # still include CORS headers so that browser fetch() surfaces the real
        # HTTP status rather than a generic network error.
        # Note: API Gateway mapping template values require the literal string
        # to be wrapped in single quotes inside the double-quoted header value.
        _cors_response_headers = {
            "Access-Control-Allow-Origin": f"'{website_url}'",
            "Access-Control-Allow-Headers": "'Content-Type'",
        }

        for response_type in (
            apigw.ResponseType.DEFAULT_4_XX,
            apigw.ResponseType.DEFAULT_5_XX,
            apigw.ResponseType.THROTTLED,
            apigw.ResponseType.UNAUTHORIZED,
        ):
            self.api.add_gateway_response(
                f"GatewayResponse{response_type.response_type.replace('_', '')}",
                type=response_type,
                response_headers=_cors_response_headers,
            )

        # Operational signals; attach notification actions as appropriate for the deployment.
        alarm_specs = [
            ("LambdaErrors", self.hit_handler.metric_errors(), "alarm_lambda_errors_threshold", 1),
            ("LambdaThrottles", self.hit_handler.metric_throttles(), "alarm_lambda_throttles_threshold", 1),
            ("Api5xx", self.api.metric_server_error(), "alarm_api_5xx_threshold", 5),
            ("DynamoDbErrors", self.table.metric_system_errors_for_operations(operations=[dynamodb.Operation.GET_ITEM, dynamodb.Operation.UPDATE_ITEM]), "alarm_ddb_errors_threshold", 1),
            ("DynamoDbThrottles", cloudwatch.Metric(namespace="AWS/DynamoDB",
                metric_name="ThrottledRequests", dimensions_map={"TableName": self.table.table_name,
                "Operation": "UpdateItem"}, statistic="Sum", period=Duration.minutes(5)),
                "alarm_ddb_throttles_threshold", 1),
        ]
        for name, metric, key, default in alarm_specs:
            cloudwatch.Alarm(self, name, metric=metric,
                threshold=float(self.node.try_get_context(key) or default),
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING)
        for key, value in {
            "WebsiteUrl": website_url, "ApiUrl": self.api.url,
            "DistributionId": self.distribution.distribution_id,
            "TableName": self.table.table_name, "BucketName": self.website_bucket.bucket_name,
            "Environment": env,
        }.items():
            cdk.CfnOutput(self, key, value=value)
        cdk.Tags.of(self).add("Environment", env)
