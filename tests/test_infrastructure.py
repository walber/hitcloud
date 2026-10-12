"""
Infrastructure unit tests for AppStack using ``aws_cdk.assertions.Template``.

Each test class is scoped to one AWS resource type / one task, making it easy
to extend this file in later tasks:

  Task 2.2  — DynamoDB Counter Table          (this task)
  Task 5.3  — Lambda IAM role                 (add to class TestLambdaIam)
  Task 7.3  — WAF WebACL association          (add to class TestWafAssociation)
  Task 8.3  — S3 bucket + CloudFront OAC      (add to class TestS3AndCloudFront)
  Task 11.2 — CloudFormation outputs + tags   (add to class TestOutputsAndTags)

All classes share a single synthesised template via a module-level fixture so
CDK synthesis runs only once per pytest session.
"""

import pytest
import aws_cdk as cdk
from aws_cdk import assertions

from hitcloud.app_stack import AppStack


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def template() -> assertions.Template:
    """Synthesise AppStack once and return an assertions.Template.

    Uses a fresh cdk.App without a real AWS environment so synthesis is
    purely local and deterministic.
    """
    app = cdk.App()
    stack = AppStack(app, "TestAppStack")
    return assertions.Template.from_stack(stack)


# ---------------------------------------------------------------------------
# Task 2.2 — DynamoDB Counter Table
# Validates: Requirements 5.1, 5.2, 5.3, 11.3
# ---------------------------------------------------------------------------

class TestDynamoDbTable:
    """Assert that the Counter Table has the correct properties."""

    def test_exactly_one_dynamodb_table(self, template: assertions.Template):
        """AppStack must contain exactly one DynamoDB table."""
        template.resource_count_is("AWS::DynamoDB::Table", 1)

    def test_billing_mode_pay_per_request(self, template: assertions.Template):
        """Table must use on-demand / PAY_PER_REQUEST billing mode (Req 5.1)."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {"BillingMode": "PAY_PER_REQUEST"},
        )

    def test_point_in_time_recovery_enabled(self, template: assertions.Template):
        """PITR must be enabled (Req 5.1)."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {
                "PointInTimeRecoverySpecification": {
                    "PointInTimeRecoveryEnabled": True,
                }
            },
        )

    def test_partition_key_is_id_string(self, template: assertions.Template):
        """Partition key must be 'id' of type String (Req 5.1)."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {
                "KeySchema": [
                    {"AttributeName": "id", "KeyType": "HASH"},
                ],
                "AttributeDefinitions": [
                    {"AttributeName": "id", "AttributeType": "S"},
                ],
            },
        )

    def test_sse_enabled(self, template: assertions.Template):
        """AWS-managed encryption at rest must be enabled (Req 5.1)."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {"SSESpecification": {"SSEEnabled": True}},
        )

    def test_deletion_protection_disabled_in_dev(self, template: assertions.Template):
        """Deletion protection must be off in the default 'dev' environment (Req 5.3)."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {"DeletionProtectionEnabled": False},
        )

    def test_removal_policy_destroy_in_dev(self, template: assertions.Template):
        """Removal policy must be DESTROY in the default 'dev' environment (Req 5.3).

        CDK expresses this as DeletionPolicy + UpdateReplacePolicy both set to
        'Delete' on the CloudFormation resource.
        """
        template.has_resource(
            "AWS::DynamoDB::Table",
            {
                "DeletionPolicy": "Delete",
                "UpdateReplacePolicy": "Delete",
            },
        )

    # --- Production environment variant ---

    def test_deletion_protection_enabled_in_production(self):
        """Deletion protection must be on when environment='production' (Req 5.2)."""
        app = cdk.App(context={"environment": "production"})
        stack = AppStack(app, "ProdStack")
        prod_template = assertions.Template.from_stack(stack)

        prod_template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {"DeletionProtectionEnabled": True},
        )

    def test_removal_policy_retain_in_production(self):
        """Removal policy must be RETAIN when environment='production' (Req 5.2)."""
        app = cdk.App(context={"environment": "production"})
        stack = AppStack(app, "ProdStackRetain")
        prod_template = assertions.Template.from_stack(stack)

        prod_template.has_resource(
            "AWS::DynamoDB::Table",
            {
                "DeletionPolicy": "Retain",
                "UpdateReplacePolicy": "Retain",
            },
        )


# ---------------------------------------------------------------------------
# Placeholder classes for future tasks — add assertions inside each class
# as the corresponding task is implemented.
# ---------------------------------------------------------------------------

class TestLambdaIam:
    """Task 5.3 — Lambda IAM role grants only UpdateItem + GetItem (Req 6.1).

    Validates: Requirements 11.3
    """

    def _get_dynamodb_statement(self, template: assertions.Template) -> dict:
        """Return the IAM policy statement that contains the DynamoDB actions."""
        policies = template.find_resources("AWS::IAM::Policy")
        for policy in policies.values():
            statements = (
                policy.get("Properties", {})
                .get("PolicyDocument", {})
                .get("Statement", [])
            )
            for stmt in statements:
                actions = stmt.get("Action", [])
                if isinstance(actions, str):
                    actions = [actions]
                if any("dynamodb:" in a for a in actions):
                    return stmt
        raise AssertionError("No IAM policy statement with dynamodb: actions found")

    def _get_all_dynamodb_actions(self, template: assertions.Template) -> list[str]:
        """Collect every DynamoDB action across all IAM policy statements."""
        actions: list[str] = []
        policies = template.find_resources("AWS::IAM::Policy")
        for policy in policies.values():
            statements = (
                policy.get("Properties", {})
                .get("PolicyDocument", {})
                .get("Statement", [])
            )
            for stmt in statements:
                stmt_actions = stmt.get("Action", [])
                if isinstance(stmt_actions, str):
                    stmt_actions = [stmt_actions]
                actions.extend(a for a in stmt_actions if "dynamodb:" in a)
        return actions

    def _get_logs_statement(self, template: assertions.Template) -> dict:
        """Return the IAM policy statement that contains the CloudWatch Logs actions."""
        policies = template.find_resources("AWS::IAM::Policy")
        for policy in policies.values():
            statements = (
                policy.get("Properties", {})
                .get("PolicyDocument", {})
                .get("Statement", [])
            )
            for stmt in statements:
                actions = stmt.get("Action", [])
                if isinstance(actions, str):
                    actions = [actions]
                if any("logs:" in a for a in actions):
                    return stmt
        raise AssertionError("No IAM policy statement with logs: actions found")

    # ── DynamoDB permission assertions ────────────────────────────────────────

    def test_dynamodb_update_item_is_granted(self, template: assertions.Template):
        """Hit Handler role must contain dynamodb:UpdateItem (Req 6.1)."""
        stmt = self._get_dynamodb_statement(template)
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        assert "dynamodb:UpdateItem" in actions, (
            f"Expected 'dynamodb:UpdateItem' in policy statement actions, got: {actions}"
        )

    def test_dynamodb_get_item_is_granted(self, template: assertions.Template):
        """Hit Handler role must contain dynamodb:GetItem (Req 6.1)."""
        stmt = self._get_dynamodb_statement(template)
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        assert "dynamodb:GetItem" in actions, (
            f"Expected 'dynamodb:GetItem' in policy statement actions, got: {actions}"
        )

    def test_dynamodb_resource_is_table_arn(self, template: assertions.Template):
        """DynamoDB permissions must be scoped to the Counter Table ARN, not '*' (Req 6.1)."""
        stmt = self._get_dynamodb_statement(template)
        resources = stmt.get("Resource", [])
        if isinstance(resources, str):
            resources = [resources]
        # The resource must not be a wildcard
        assert "*" not in resources, (
            "DynamoDB permissions must not use a wildcard resource"
        )
        # The resource must reference the table via Fn::GetAtt, not an arbitrary ARN
        assert any(
            isinstance(r, dict) and "Fn::GetAtt" in r for r in resources
        ), (
            f"Expected the DynamoDB resource to be a Fn::GetAtt reference to the table, got: {resources}"
        )

    def test_no_dynamodb_wildcard_action(self, template: assertions.Template):
        """The policy must NOT contain 'dynamodb:*' (Req 6.1)."""
        all_dynamo_actions = self._get_all_dynamodb_actions(template)
        assert "dynamodb:*" not in all_dynamo_actions, (
            "Policy must NOT grant the broad 'dynamodb:*' permission"
        )

    def test_no_broad_dynamodb_actions(self, template: assertions.Template):
        """Only UpdateItem and GetItem should appear; no other DynamoDB actions allowed (Req 6.1)."""
        all_dynamo_actions = self._get_all_dynamodb_actions(template)
        allowed = {"dynamodb:UpdateItem", "dynamodb:GetItem"}
        extra = set(all_dynamo_actions) - allowed
        assert not extra, (
            f"Policy contains unexpected DynamoDB actions beyond UpdateItem/GetItem: {extra}"
        )

    # ── CloudWatch Logs permission assertions ─────────────────────────────────

    def test_logs_create_log_group_is_granted(self, template: assertions.Template):
        """Hit Handler role must contain logs:CreateLogGroup (Req 6.2)."""
        stmt = self._get_logs_statement(template)
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        assert "logs:CreateLogGroup" in actions, (
            f"Expected 'logs:CreateLogGroup' in policy statement actions, got: {actions}"
        )

    def test_logs_create_log_stream_is_granted(self, template: assertions.Template):
        """Hit Handler role must contain logs:CreateLogStream (Req 6.2)."""
        stmt = self._get_logs_statement(template)
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        assert "logs:CreateLogStream" in actions, (
            f"Expected 'logs:CreateLogStream' in policy statement actions, got: {actions}"
        )

    def test_logs_put_log_events_is_granted(self, template: assertions.Template):
        """Hit Handler role must contain logs:PutLogEvents (Req 6.2)."""
        stmt = self._get_logs_statement(template)
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        assert "logs:PutLogEvents" in actions, (
            f"Expected 'logs:PutLogEvents' in policy statement actions, got: {actions}"
        )

    def test_logs_permissions_scoped_to_log_group(self, template: assertions.Template):
        """Logs permissions must be scoped to the function's own log group ARN (Req 6.2)."""
        stmt = self._get_logs_statement(template)
        resources = stmt.get("Resource", [])
        if isinstance(resources, str):
            resources = [resources]
        # Must not be a wildcard
        assert "*" not in resources, (
            "Logs permissions must not use a wildcard resource"
        )
        # At least one resource must reference the log group via Fn::GetAtt
        assert any(
            isinstance(r, dict) and "Fn::GetAtt" in r for r in resources
        ), (
            f"Expected at least one Fn::GetAtt reference to the log group in logs resources, got: {resources}"
        )


class TestWafAssociation:
    """Task 7.3 — WAF WebACL is associated with the API Gateway stage (Req 7.1).

    Validates: Requirements 11.3
    """

    def test_waf_association_resource_exists(self, template: assertions.Template):
        """Exactly one WAFv2 WebACL association must exist in the template (Req 7.1)."""
        template.resource_count_is("AWS::WAFv2::WebACLAssociation", 1)

    def test_resource_arn_references_api_gateway_stage(
        self, template: assertions.Template
    ):
        """ResourceArn must reference an API Gateway stage
        (contains '/restapis/' and '/stages/' segments) (Req 3.3, 7.1).

        The CDK constructs the ARN as an ``Fn::Join`` of an empty-string
        delimiter and a parts array. We verify both literal substrings are
        present in the join parts using ``Match.object_like`` so the assertion
        is tolerant of the dynamic pieces (region Ref, API ID Ref, stage name).
        """
        # The synthesised ResourceArn looks like:
        # {"Fn::Join": ["", ["arn:aws:apigateway:", {"Ref": "AWS::Region"},
        #   "::/restapis/", {"Ref": "<ApiId>"}, "/stages/<env>"]]}
        # We assert the two identifying substrings exist in the parts array.
        resources = template.find_resources("AWS::WAFv2::WebACLAssociation")
        assert resources, "No AWS::WAFv2::WebACLAssociation resource found"
        for resource in resources.values():
            resource_arn = resource.get("Properties", {}).get("ResourceArn", {})
            join = resource_arn.get("Fn::Join", [])
            assert len(join) == 2, (
                f"Expected Fn::Join with 2 elements, got: {join}"
            )
            parts = join[1]
            assert isinstance(parts, list), (
                f"Expected Fn::Join parts to be a list, got: {parts}"
            )
            parts_str = str(parts)
            assert "/restapis/" in parts_str, (
                f"Expected '/restapis/' in ResourceArn join parts, got: {parts}"
            )
            assert "/stages/" in parts_str, (
                f"Expected '/stages/' in ResourceArn join parts, got: {parts}"
            )

    def test_web_acl_arn_uses_get_att(self, template: assertions.Template):
        """WebACLArn must reference the WAF WebACL via ``Fn::GetAtt`` (Req 7.1)."""
        template.has_resource_properties(
            "AWS::WAFv2::WebACLAssociation",
            {
                "WebACLArn": assertions.Match.object_like(
                    {"Fn::GetAtt": assertions.Match.any_value()}
                )
            },
        )


class TestS3AndCloudFront:
    """Task 8.3 — S3 public access block + CloudFront OAC (Req 2.1, 2.2).

    Validates: Requirements 11.3
    """

    # ── S3 Block Public Access assertions ─────────────────────────────────────

    def test_s3_block_public_acls(self, template: assertions.Template):
        """S3 bucket must have BlockPublicAcls=True (Req 2.1)."""
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                }
            },
        )

    def test_s3_block_public_policy(self, template: assertions.Template):
        """S3 bucket must have BlockPublicPolicy=True (Req 2.1)."""
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicPolicy": True,
                }
            },
        )

    def test_s3_ignore_public_acls(self, template: assertions.Template):
        """S3 bucket must have IgnorePublicAcls=True (Req 2.1)."""
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "IgnorePublicAcls": True,
                }
            },
        )

    def test_s3_restrict_public_buckets(self, template: assertions.Template):
        """S3 bucket must have RestrictPublicBuckets=True (Req 2.1)."""
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "RestrictPublicBuckets": True,
                }
            },
        )

    def test_s3_all_four_block_public_access_fields_true(
        self, template: assertions.Template
    ):
        """All four Block Public Access fields must be True in a single assertion (Req 2.1)."""
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                }
            },
        )

    # ── CloudFront OAC assertions ─────────────────────────────────────────────

    def test_cloudfront_oac_resource_exists(self, template: assertions.Template):
        """Exactly one AWS::CloudFront::OriginAccessControl resource must exist (Req 2.2)."""
        template.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)

    def test_cloudfront_oac_signing_is_sigv4_always(
        self, template: assertions.Template
    ):
        """OAC must use sigv4 signing protocol with 'always' behavior (Req 2.2)."""
        template.has_resource_properties(
            "AWS::CloudFront::OriginAccessControl",
            {
                "OriginAccessControlConfig": {
                    "OriginAccessControlOriginType": "s3",
                    "SigningBehavior": "always",
                    "SigningProtocol": "sigv4",
                }
            },
        )

    def test_cloudfront_distribution_origin_uses_oac_id(
        self, template: assertions.Template
    ):
        """The distribution's S3 origin must reference the OAC via OriginAccessControlId (Req 2.2)."""
        # Find all CloudFront::OriginAccessControl resources and collect their
        # logical IDs so we can verify the distribution references one of them.
        oac_resources = template.find_resources(
            "AWS::CloudFront::OriginAccessControl"
        )
        assert oac_resources, "No AWS::CloudFront::OriginAccessControl resource found"
        oac_logical_ids = list(oac_resources.keys())

        distributions = template.find_resources("AWS::CloudFront::Distribution")
        assert distributions, "No AWS::CloudFront::Distribution resource found"

        for dist_resource in distributions.values():
            origins = (
                dist_resource.get("Properties", {})
                .get("DistributionConfig", {})
                .get("Origins", [])
            )
            for origin in origins:
                oac_id_ref = origin.get("OriginAccessControlId", {})
                # CDK sets OriginAccessControlId as Fn::GetAtt of the OAC resource.
                get_att = oac_id_ref.get("Fn::GetAtt", [])
                if get_att and get_att[0] in oac_logical_ids:
                    return  # found a valid OAC reference — test passes

        raise AssertionError(
            "No CloudFront distribution origin references an OAC via OriginAccessControlId"
        )

    def test_cloudfront_distribution_s3_origin_has_no_oai(
        self, template: assertions.Template
    ):
        """The distribution's S3 origin must NOT use a legacy OAI
        (S3OriginConfig.OriginAccessIdentity must be absent or empty) (Req 2.2).

        When CDK uses OAC it still emits ``S3OriginConfig`` with an empty
        ``OriginAccessIdentity`` string.  This test asserts the value is NOT
        a real OAI identity path (e.g. 'origin-access-identity/cloudfront/XXXXX').
        """
        distributions = template.find_resources("AWS::CloudFront::Distribution")
        assert distributions, "No AWS::CloudFront::Distribution resource found"

        for dist_resource in distributions.values():
            origins = (
                dist_resource.get("Properties", {})
                .get("DistributionConfig", {})
                .get("Origins", [])
            )
            for origin in origins:
                s3_origin_config = origin.get("S3OriginConfig", {})
                oai_value = s3_origin_config.get("OriginAccessIdentity", "")
                # A real OAI always starts with
                # 'origin-access-identity/cloudfront/'.  An empty string means
                # no OAI is set (OAC pattern).
                assert not (
                    isinstance(oai_value, str)
                    and oai_value.startswith("origin-access-identity/cloudfront/")
                ), (
                    f"S3 origin should NOT use a legacy OAI, "
                    f"but OriginAccessIdentity is: '{oai_value}'"
                )

    # ── S3 bucket policy SSL enforcement assertion ────────────────────────────

    def test_s3_bucket_policy_denies_non_ssl(self, template: assertions.Template):
        """S3 bucket policy must include a Deny statement for non-SSL access (Req 2.1).

        CDK's ``enforce_ssl=True`` adds a statement with:
          Effect: Deny
          Action: s3:*
          Condition: Bool: aws:SecureTransport: "false"
        """
        bucket_policies = template.find_resources("AWS::S3::BucketPolicy")
        assert bucket_policies, "No AWS::S3::BucketPolicy resource found"

        for policy in bucket_policies.values():
            statements = (
                policy.get("Properties", {})
                .get("PolicyDocument", {})
                .get("Statement", [])
            )
            for stmt in statements:
                if stmt.get("Effect") != "Deny":
                    continue
                condition = stmt.get("Condition", {})
                bool_condition = condition.get("Bool", {})
                secure_transport = bool_condition.get("aws:SecureTransport", None)
                # CDK emits the value as the string "false"
                if secure_transport == "false":
                    return  # found the Deny-non-SSL statement

        raise AssertionError(
            "No Deny statement with Condition.Bool.aws:SecureTransport='false' "
            "found in the S3 bucket policy. "
            "Make sure enforce_ssl=True is set on the S3 bucket."
        )


class TestOutputsAndTags:
    """Task 11.2 — CloudFormation outputs + Environment tag (Req 1.5, 1.6)."""
    pass  # assertions added in task 11.2


def test_outputs_tags_and_alarms(template):
    raw = template.to_json()
    assert {'WebsiteUrl', 'ApiUrl', 'DistributionId', 'TableName', 'BucketName', 'Environment'} <= raw['Outputs'].keys()
    template.has_resource_properties('AWS::DynamoDB::Table', {'Tags': [{'Key': 'Environment', 'Value': 'dev'}]})
    template.resource_count_is('AWS::CloudWatch::Alarm', 5)
    for alarm in template.find_resources('AWS::CloudWatch::Alarm').values():
        assert alarm['Properties']['TreatMissingData'] == 'notBreaching'


def test_csp_cors_and_stage_dependency(template):
    import json
    raw = template.to_json()
    policy = next(iter(template.find_resources('AWS::CloudFront::ResponseHeadersPolicy').values()))
    csp = policy['Properties']['ResponseHeadersPolicyConfig']['SecurityHeadersConfig']['ContentSecurityPolicy']
    assert "connect-src 'self'" in json.dumps(csp)
    assert 'execute-api' in json.dumps(csp)
    function = next(iter(template.find_resources('AWS::Lambda::Function').values()))
    assert function['Properties']['Environment']['Variables']['ALLOWED_ORIGIN'] != '*'
    assoc = next(iter(template.find_resources('AWS::WAFv2::WebACLAssociation').values()))
    stages = template.find_resources('AWS::ApiGateway::Stage')
    assert set(stages) & set(assoc['DependsOn'])
    # Detect cycles that can be missed by source-code inspection.
    resources = raw['Resources']
    def refs(value):
        result = set()
        if isinstance(value, dict):
            if 'Ref' in value and value['Ref'] in resources: result.add(value['Ref'])
            if 'Fn::GetAtt' in value: result.add(value['Fn::GetAtt'][0])
            for child in value.values(): result |= refs(child)
        elif isinstance(value, list):
            for child in value: result |= refs(child)
        return result
    graph = {key: refs(value) | set(value.get('DependsOn', [])) for key, value in resources.items()}
    done = set()
    def visit(key, path):
        assert key not in path, f'CloudFormation cycle: {path} -> {key}'
        if key in done: return
        for child in graph.get(key, set()): visit(child, path + [key])
        done.add(key)
    for key in graph: visit(key, [])


def test_custom_domain_has_dns_and_imported_certificate():
    app = cdk.App(context={'domain_name': 'counter.example.com', 'hosted_zone_id': 'ZTEST', 'hosted_zone_name': 'example.com'})
    stack = AppStack(app, 'CustomTest', env=cdk.Environment(account='111111111111', region='us-east-2'),
        certificate_arn='arn:aws:acm:us-east-1:111111111111:certificate/test')
    template = assertions.Template.from_stack(stack)
    template.resource_count_is('AWS::Route53::RecordSet', 2)
    template.has_resource_properties('AWS::CloudFront::Distribution', {'DistributionConfig': {
        'Aliases': ['counter.example.com'], 'ViewerCertificate': {
            'AcmCertificateArn': 'arn:aws:acm:us-east-1:111111111111:certificate/test'}}})
    assert template.to_json()['Outputs']['WebsiteUrl']['Value'] == 'https://counter.example.com'


def test_certificate_uses_dns_validation():
    from hitcloud.cert_stack import CertStack
    app = cdk.App(context={'domain_name': 'counter.example.com', 'hosted_zone_id': 'ZTEST', 'hosted_zone_name': 'example.com'})
    stack = CertStack(app, 'CertTest', env=cdk.Environment(account='111111111111', region='us-east-1'))
    assertions.Template.from_stack(stack).has_resource_properties('AWS::CertificateManager::Certificate', {
        'DomainName': 'counter.example.com', 'ValidationMethod': 'DNS'})
