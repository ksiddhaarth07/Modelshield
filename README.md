# ModelShield

**A self-optimising, serverless AI incident-triage gateway on AWS.**
`API Gateway → Lambda → Amazon Bedrock → DynamoDB → CloudWatch`, deployed twice
(`modelshield-v1` vs `modelshield-v2`) so the cost, latency and sustainability
delta can be measured live on the same 100-ticket benchmark.

ModelShield is a worked example of a problem almost every production GenAI
backend has: **every ticket goes to the most expensive model, forever.** The v1
stack is that conventional baseline. The v2 stack adds a fail-open DynamoDB TTL
cache and a confidence-gated Nova Micro → Nova Pro router, then proves the
result instead of asserting it.

## Before / After

| Dimension | `v1-before` | `v2-after` |
| --- | --- | --- |
| Compute | Lambda `python3.13`, **x86_64**, **512 MB** | Lambda `python3.13`, **arm64**, **256 MB** |
| Routing | 100% synchronous Nova Pro | TTL cache → complexity gate → Nova Micro → confidence/P1 escalation to Nova Pro |
| Repeat traffic | Full frontier inference every time | Normalised SHA-256 key, DynamoDB **24h TTL**, `$0.00` model cost |
| API protection | HTTP API + CORS | HTTP API + CORS + **25 req/s, burst 50** |
| Data | `TicketsTable` | `TicketsTable` + `ResponseCacheTable` |
| Failure mode | Provider error → 502 | Cache fail-open; Micro error → Pro fallback; Pro error → 502 |
| Observability | EMF + CloudWatch dashboard | Same, plus cache/escalation/fallback counters |
| Package | Pure stdlib + runtime boto3 (no native wheels) | Same, which is what makes the Docker-free arm64 build possible |

Measured headline numbers are written to `eval/results/benchmark_report.json` by
`eval/run_benchmark.py` and summarised here once the two stacks are live.

## Architecture

```
                         ┌──────────────────────────────┐
   POST /triage          │  API Gateway HTTP API (CORS)  │
   GET  /health   ──────▶│  v2 adds 25 r/s + burst 50    │
   GET  /stats           └──────────────┬───────────────┘
                                        │
                              ┌─────────▼─────────┐
                              │  Lambda python3.13 │
                              │  x86_64 512MB (v1) │
                              │  arm64  256MB (v2) │
                              └─────────┬─────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
     ┌────────▼────────┐      ┌─────────▼─────────┐     ┌─────────▼─────────┐
     │ ResponseCache   │      │  Complexity gate  │     │  Amazon Bedrock   │
     │ DynamoDB, 24h   │      │  keywords + size  │     │  Nova Micro / Pro │
     │ fail-open (v2)  │      └───────────────────┘     └───────────────────┘
     └─────────────────┘
              │
     ┌────────▼────────┐      ┌────────────────────┐
     │  TicketsTable   │      │ CloudWatch EMF     │
     │  DynamoDB       │      │ ModelShield/Triage │
     └─────────────────┘      └────────────────────┘
```

Every request emits one CloudWatch EMF document (namespace
`ModelShield/Triage`, dimension `StackVersion`) and the SAM template provisions
the dashboard that plots average cost, p95 latency, frontier tokens, cache hits,
escalations and GB-seconds side by side.

## API

`POST /triage`

```json
{
  "ticket_id": "tkt-042",
  "subject": "Checkout webhooks timing out after regional failover",
  "body": "Multiple enterprise tenants report 503 errors on payment confirmation webhooks since 04:12 UTC..."
}
```

```json
{
  "ticket_id": "tkt-042",
  "severity": "P1",
  "category": "incident",
  "confidence": 0.96,
  "summary": "Regional failover causing 503 timeouts on enterprise payment webhooks.",
  "draft_reply": "We have escalated this P1 payment webhook outage to our on-call SRE team...",
  "telemetry": {
    "stack_version": "v1",
    "route_decision": "single_heavy",
    "model_id": "us.amazon.nova-pro-v1:0",
    "cache_hit": false,
    "escalated": false,
    "fallback_triggered": false,
    "input_tokens": 286,
    "output_tokens": 114,
    "frontier_tokens_used": 400,
    "estimated_cost_usd": 0.0005936,
    "latency_ms": 1140,
    "lambda_memory_mb": 512,
    "lambda_gb_seconds": 0.57,
    "architecture": "x86_64"
  }
}
```

`severity` ∈ `P1..P4`; `category` ∈ `incident, security, billing, account, how_to, bug`;
`route_decision` ∈ `single_heavy, cache_hit, nova_micro, escalated_pro, direct_pro, fallback_pro`.

`GET /health` is a dependency-free liveness probe. `GET /stats` scans
`TicketsTable` and returns severity/category rollups, p95 latency, spend and
cache/escalation counts.

## Deploy

Prerequisites: AWS CLI v2 with credentials, SAM CLI, and Bedrock model access to
`us.amazon.nova-pro-v1:0` (and `us.amazon.nova-micro-v1:0` for v2) in `us-east-1`.

```powershell
# v1 (x86_64 / Nova Pro baseline)
./deploy.ps1 -Env v1

# v2 (arm64 / cache + adaptive router)
./deploy.ps1 -Env v2
```

Or by hand:

```powershell
sam build --template-file infra/template.yaml --config-file infra/samconfig.toml
sam deploy --config-env v1 --config-file infra/samconfig.toml --template-file .aws-sam/build/template.yaml
sam deploy --config-env v2 --config-file infra/samconfig.toml --template-file .aws-sam/build/template.yaml
```

Both stacks are 100% on-demand serverless, so idle cost is effectively zero.
`./deploy.ps1` prints the stack outputs (`ApiUrl`, `HealthUrl`,
`TriageTableName`, `DashboardName`).

## Local development

```powershell
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest          # 34 tests, no AWS calls
```

The Lambda handler is framework-free and covered with a fake Bedrock client, so
validation, telemetry, persistence-failure and model-output-recovery paths are
all tested offline.

## Repository layout

```
infra/template.yaml       SAM: HTTP API, Lambda, DynamoDB, IAM, logs, dashboard
infra/samconfig.toml      [v1] and [v2] deployment profiles
backend/src/handler.py    routing + response contract
backend/src/schemas.py    request validation + defensive output parsing
backend/src/prompts.py    deterministic triage prompt
backend/src/bedrock_client.py  Converse wrapper, jittered retries, exact USD cost
backend/src/storage.py    DynamoDB writes + /stats rollup
backend/src/metrics.py    CloudWatch EMF emitter
backend/tests/            offline contract + handler tests
eval/                     100-ticket benchmark (dataset + async runner)
frontend/                 live benchmark deck (React + TS + Vite)
docs/                     Well-Architected before/after reports and diff
```

## Design notes

- **Fail-open by default.** Cache read/write and ticket persistence degrade to a
  logged warning; only a failed model call produces a 5xx.
- **Honest accounting.** An escalated request is billed as Micro + Pro tokens,
  not as Micro. Cost per *successful* ticket is the headline metric, not cost per
  request.
- **Least privilege.** The role can `InvokeModel` on exactly one inference
  profile and its foundation-model ARN, and can touch exactly one table.
- **No Docker.** Zero native wheels means `sam build` produces an arm64 zip
  anywhere, including Windows.

## Status

- `v1-before` implemented and unit-tested; template validates and builds.
- Live deployment is pending AWS account verification (Bedrock returns
  `AccessDeniedException: Your account is currently being verified`) and an
  Organizations SCP that denies DynamoDB/CloudFormation/Lambda on the current
  deployment identity.
- `v2-after`, the 100-ticket benchmark, Well-Architected reports and the live
  deck land on the `feat/war-tiered-model-router` branch.
