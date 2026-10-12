from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_certificatemanager as acm, aws_route53 as route53
from constructs import Construct

class CertStack(Stack):
    """Certificate in us-east-1. Pass the output ARN explicitly to the regional stack."""
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        domain = self.node.try_get_context("domain_name")
        zone = route53.HostedZone.from_hosted_zone_attributes(self, "Zone",
            hosted_zone_id=self.node.try_get_context("hosted_zone_id"),
            zone_name=self.node.try_get_context("hosted_zone_name") or domain)
        self.certificate = acm.Certificate(self, "Certificate", domain_name=domain,
            validation=acm.CertificateValidation.from_dns(zone))
        CfnOutput(self, "CertificateArn", value=self.certificate.certificate_arn)
