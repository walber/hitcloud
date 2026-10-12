"""Explicit opt-in only; reads stack tags/outputs to reject production targets."""
import json
import os
from urllib.request import Request, urlopen
import boto3
import pytest


def test_live_counter_increments():
    if os.environ.get('INTEGRATION_TEST') != 'true':
        pytest.skip('Set INTEGRATION_TEST=true only for an isolated test stack')
    context = json.load(open('cdk.json'))['context']
    if context.get('environment') == 'production':
        pytest.skip('Never run counter integration tests in production')
    stack_name = os.environ.get('INTEGRATION_STACK_NAME')
    if not stack_name:
        pytest.fail('INTEGRATION_STACK_NAME must identify an isolated deployed test stack')
    stack = boto3.client('cloudformation', region_name='us-east-2').describe_stacks(
        StackName=stack_name)['Stacks'][0]
    outputs = {o['OutputKey']: o['OutputValue'] for o in stack.get('Outputs', [])}
    tags = {t['Key']: t['Value'] for t in stack.get('Tags', [])}
    if outputs.get('Environment') not in ('dev', 'test') or tags.get('Environment') not in ('dev', 'test'):
        pytest.skip('Stack environment is production, unknown, or not explicitly dev/test')
    api = outputs['ApiUrl'].rstrip('/')
    n = int(os.environ.get('INTEGRATION_HITS', '5'))
    if not 1 <= n <= 20:
        pytest.fail('INTEGRATION_HITS must be 1..20')
    def request(path, method='GET'):
        req = Request(f'{api}/{path}', method=method)
        with urlopen(req, timeout=10) as result:
            return json.load(result)['count']
    before = request('count')
    for _ in range(n):
        request('hit', 'POST')  # Deliberately no retry.
    assert request('count') == before + n, 'Use a stack with no other traffic or ambiguous failures'
