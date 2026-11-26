param(
    [ValidateSet("v1", "v2")]
    [string]$Env = "v1"
)

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    Write-Host "Building ModelShield..." -ForegroundColor Cyan
    sam build --template-file infra/template.yaml --config-file infra/samconfig.toml
    if ($LASTEXITCODE -ne 0) { throw "sam build failed ($LASTEXITCODE)" }

    Write-Host "Deploying stack profile '$Env'..." -ForegroundColor Cyan
    sam deploy --config-env $Env --config-file infra/samconfig.toml --template-file .aws-sam/build/template.yaml
    if ($LASTEXITCODE -ne 0) { throw "sam deploy failed ($LASTEXITCODE)" }

    Write-Host "Done. Fetch outputs with:" -ForegroundColor Green
    Write-Host "  aws cloudformation describe-stacks --stack-name modelshield-$Env --query 'Stacks[0].Outputs'"
}
finally {
    Pop-Location
}
