#!/usr/bin/env python3
"""Synthesize locally. deploy.sh handles explicit, two-phase certificate deployment."""
import os
import aws_cdk as cdk
from aws_cdk import aws_certificatemanager as acm
from hitcloud.app_stack import AppStack
from hitcloud.cert_stack import CertStack

app = cdk.App()
account = app.node.try_get_context("aws_account") or os.environ.get("CDK_DEFAULT_ACCOUNT")
domain = app.node.try_get_context("domain_name")
zone = app.node.try_get_context("hosted_zone_id")
if bool(domain) != bool(zone):
    raise ValueError("Set both domain_name and hosted_zone_id, or neither")
certificate_arn = app.node.try_get_context("certificate_arn")
cert_only = str(app.node.try_get_context("certificate_only")).lower() == "true"
if domain:
    CertStack(app, "CertStack", env=cdk.Environment(account=account, region="us-east-1"))
if not cert_only:
    if domain and not certificate_arn:
        raise ValueError("Deploy CertStack with -c certificate_only=true, then pass its ARN using -c certificate_arn=...")
    stack = AppStack(app, "AppStack",
        env=cdk.Environment(account=account, region="us-east-2"),
        certificate_arn=certificate_arn)
app.synth()
