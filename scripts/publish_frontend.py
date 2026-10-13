"""Upload built assets, runtime configuration, then HTML; preserve old hashed assets."""
import argparse
import json
from pathlib import Path
import subprocess


def publish(outputs_path, dist=Path('frontend/dist')):
    outputs = json.loads(Path(outputs_path).read_text())['AppStack']
    api, bucket, distribution = (outputs[k] for k in ('ApiUrl', 'BucketName', 'DistributionId'))
    if not (dist / 'index.html').is_file():
        raise ValueError('Build frontend before publishing')
    (dist / 'config.json').write_text(json.dumps({'apiUrl': api.rstrip('/')}) + '\n')
    def aws(*args):
        subprocess.run(['aws', *args, '--region', 'us-east-2'], check=True)

    asset_cache = "public,max-age=31536000,immutable"
    assets_url = f"s3://{bucket}/assets/"

    # Keep old hashed assets so clients with cached HTML are not broken during rollout.
    aws('s3', 'sync', str(dist / 'assets'), f's3://{bucket}/assets/',
        '--cache-control', asset_cache)
    # JavaScript is uploaded separately with an explicit MIME type.
    aws(
        "s3", "sync", str(dist / "assets"), assets_url,
        "--exclude", "*.js",
        "--cache-control", asset_cache,
    )
    # Re-upload JavaScript even when unchanged to correct existing metadata.
    aws(
        "s3", "cp", str(dist / "assets"), assets_url,
        "--recursive",
        "--exclude", "*",
        "--include", "*.js",
        "--content-type", "text/javascript",
        "--cache-control", asset_cache,
    )
    aws('s3', 'cp', str(dist / 'config.json'), f's3://{bucket}/config.json',
        '--cache-control', 'no-store', '--content-type', 'application/json')
    aws('s3', 'cp', str(dist / 'index.html'), f's3://{bucket}/index.html',
        '--cache-control', 'no-cache,max-age=0,must-revalidate',
        '--content-type', 'text/html; charset=utf-8')
    aws('cloudfront', 'create-invalidation', '--distribution-id', distribution,
        '--paths', '/', '/index.html', '/config.json')
    print('Published:', outputs['WebsiteUrl'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--outputs', default='cdk-outputs.json')
    args = parser.parse_args()
    publish(args.outputs)
