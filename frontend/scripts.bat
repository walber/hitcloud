## 0. Get Account identity
$hitcloudAccount = aws sts get-caller-identity --profile hitcloud --query Account --output text

## 1. Bootstrap the project
npx cdk bootstrap "aws://$hitcloudAccount/us-east-2" --profile hitcloud --app "python.exe app.py"

## 2. Publish frontend and deploy stack
npm --prefix frontend ci --include=dev
npm --prefix frontend run build
npx cdk deploy

## 4. Publish the web page
$env:AWS_PROFILE = "hitcloud"
$env:AWS_DEFAULT_REGION = "us-east-2"
$env:AWS_REGION = "us-east-2"

# Retrieve the deployed application's configuration
$stackOutputs = aws cloudformation describe-stacks `
  --stack-name AppStack `
  --region us-east-2 `
  --profile hitcloud `
  --query "Stacks[0].Outputs" `
  --output json `
  --no-cli-pager

if ($LASTEXITCODE -ne 0) {
  throw "Could not retrieve the deployment outputs."
}

$outputMap = @{}
($stackOutputs | ConvertFrom-Json) | ForEach-Object {
  $outputMap[$_.OutputKey] = $_.OutputValue
}

@{ AppStack = $outputMap } |
  ConvertTo-Json -Depth 5 |
  Set-Content -Path cdk-outputs.json -Encoding ASCII

# Upload the frontend and refresh CloudFront's cache
python.exe scripts/publish_frontend.py --outputs cdk-outputs.json

## Get CloudFront URL
aws cloudformation describe-stacks `
  --stack-name AppStack `
  --region us-east-2 `
  --profile hitcloud `
  --query "Stacks[0].Outputs[?OutputKey=='WebsiteUrl'].OutputValue | [0]" `
  --output text `
  --no-cli-pager

## Fix content type to "text/javascript"
$hitcloudOutputs = (Get-Content cdk-outputs.json -Raw | ConvertFrom-Json).AppStack

# Re-upload JavaScript with the correct content type
aws s3 cp frontend/dist/assets/ "s3://$($hitcloudOutputs.BucketName)/assets/" `
  --recursive `
  --exclude "*" `
  --include "*.js" `
  --content-type "text/javascript" `
  --cache-control "public,max-age=31536000,immutable" `
  --region us-east-2 `
  --profile hitcloud

if ($LASTEXITCODE -ne 0) {
  throw "JavaScript upload failed."
}

## Clear CloudFront's cached asset responses
aws cloudfront create-invalidation `
  --distribution-id $hitcloudOutputs.DistributionId `
  --paths "/assets/*" `
  --profile hitcloud `
  --no-cli-pager


## Reset counter
$hitcloudOutputs = (Get-Content cdk-outputs.json -Raw | ConvertFrom-Json).AppStack

aws dynamodb update-item `
  --table-name $hitcloudOutputs.TableName `
  --key "id={S=hits}" `
  --update-expression "SET #c = :zero" `
  --expression-attribute-names "#c=count" `
  --expression-attribute-values ":zero={N=0}" `
  --return-values ALL_NEW `
  --region us-east-2 `
  --profile hitcloud `
  --no-cli-pager

## Destroy Stack
npx cdk destroy AppStack `                                                                       
--profile hitcloud `     
--app "python.exe app.py"

aws cloudformation delete-stack `
--stack-name CDKToolkit `
--region us-east-2 `
--profile hitcloud

aws cloudformation wait stack-delete-complete `
--stack-name CDKToolkit `
--region us-east-2 `
--profile hitcloud