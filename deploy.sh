#!/usr/bin/env bash
# Run from Bash (WSL recommended on Windows). No AWS writes with --dry-run.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
mode="deploy"
if [[ ${1:-} == --dry-run ]]; then mode="dry"; shift; fi
if [[ ${1:-} == --help ]]; then
  echo 'Usage: ./deploy.sh [--dry-run] [-c key=value ...]'
  echo 'Uses AWS_PROFILE/default credential chain; deploys regional resources in us-east-2.'
  exit 0
fi
context_args=("$@")
# Install dependencies first as documented; deployment must not change the lockfile.
npm --prefix frontend ci
npm --prefix frontend run build
context_value() {
  python - "$1" "${context_args[@]}" <<'PY'
import json, sys
value = json.load(open('cdk.json')).get('context', {}).get(sys.argv[1], '')
args = sys.argv[2:]
for i, arg in enumerate(args):
    if arg in ('-c', '--context') and i+1 < len(args):
        key, sep, val = args[i+1].partition('=')
        if sep and key == sys.argv[1]: value = val
print(value)
PY
}
domain="$(context_value domain_name)"
if [[ -n "$domain" ]]; then
  if [[ "$mode" == dry ]]; then
    npx cdk synth CertStack "${context_args[@]}" -c certificate_only=true --quiet
    echo 'Certificate template validated. AppStack custom-domain synthesis requires a real certificate_arn; see README.'
    cert_arn="$(context_value certificate_arn)"
    [[ -n "$cert_arn" ]] || exit 0
  else
    npx cdk deploy CertStack "${context_args[@]}" -c certificate_only=true --outputs-file cert-outputs.json
    cert_arn="$(python -c 'import json; print(json.load(open("cert-outputs.json"))["CertStack"]["CertificateArn"])')"
    context_args+=(-c "certificate_arn=$cert_arn")
  fi
fi
npx cdk synth AppStack "${context_args[@]}" --quiet
[[ "$mode" != dry ]] || exit 0
# Review the concrete changes before deployment. CDK retains its security approval prompts.
npx cdk diff AppStack "${context_args[@]}"
npx cdk deploy AppStack "${context_args[@]}" --outputs-file cdk-outputs.json
python scripts/publish_frontend.py --outputs cdk-outputs.json
