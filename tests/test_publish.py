import json
from unittest.mock import patch
from scripts.publish_frontend import publish


def test_publish_order_and_cache_policies(tmp_path):
    dist = tmp_path / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'index.html').write_text('<html></html>')
    outputs = tmp_path / 'outputs.json'
    outputs.write_text(json.dumps({'AppStack': {'ApiUrl': 'https://api.example/dev/',
        'BucketName': 'test-bucket', 'DistributionId': 'TEST', 'WebsiteUrl': 'https://site.example'}}))
    with patch('scripts.publish_frontend.subprocess.run') as run:
        publish(outputs, dist)
    assert json.loads((dist / 'config.json').read_text())['apiUrl'] == 'https://api.example/dev'
    calls = [call.args[0] for call in run.call_args_list]
    assert calls[0][1:3] == ['s3', 'sync']
    assert '--delete' not in calls[0]
    assert 'no-store' in calls[1]
    assert 'text/html; charset=utf-8' in calls[2]
    assert calls[3][1:3] == ['cloudfront', 'create-invalidation']
