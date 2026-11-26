# ModelShield

**A self-optimising, serverless AI incident-triage gateway on AWS.**
`API Gateway → Lambda → Amazon Bedrock → DynamoDB → CloudWatch`, deployed twice
(`modelshield-v1` vs `modelshield-v2`) so the cost, latency and sustainability
delta can be measured live on the same 100-ticket benchmark.

ModelShield is a worked example of a problem almost every production GenAI
backend has: **every ticket goes to the most expensive model, forever.** The v1
stack is that conventional baseline. The v2 stack adds a fail-open DynamoDB TTL
cache and a confidence-gated Nova Lite → Nova Pro router, then proves the
result instead of asserting it.

## Before / After

| Dimension | `v1-before` | `v2-after` |
| --- | --- | --- |
| Compute | Lambda `python3.13`, **x86_64**, **512 MB** | Lambda `python3.13`, **arm64**, **256 MB** |
| Routing | 100% synchronous Nova Pro | TTL cache → complexity gate → Nova Lite → confidence/P1 escalation to Nova Pro |
| Repeat traffic | Full frontier inference every time | Normalised SHA-256 key, DynamoDB **24h TTL**, `$0.00` model cost |
| API protection | HTTP API + CORS | HTTP API + CORS + **25 req/s, burst 50** |
| Data | `TicketsTable` | `TicketsTable` + `ResponseCacheTable` |
| Failure mode | Provider error → 502 | Cache fail-open; Lite error → Pro fallback; Pro error → 502 |
| Observability | EMF + CloudWatch dashboard | Same, plus cache/escalation/fallback counters |
| Package | Pure stdlib + runtime boto3 (no native wheels) | Same, which is what makes the Docker-free arm64 build possible |

Measured headline numbers from `eval/results/benchmark_report.json` (`ap-southeast-2`, 100 tickets, concurrency 2, pacing 2.5 s):

| Metric | `v1-before` | `v2-after` | Delta |
| --- | --- | --- | --- |
| Accuracy | **94.0%** | **92.0%** | `-2.00 pp` |
| P1 Recall | **100%** (`11/11`) | **100%** (`11/11`) | `0.00 pp` |
| Cost / 10K Tickets | `$18.6717` | **`$3.3000`** | **`-82.33%`** |
| Cost / Successful Ticket | `$0.001986` | **`$0.000359`** | **`-81.94%`** |
| p95 Latency | `929 ms` | **`815 ms`** | **`-12.28%`** |
| Frontier Tokens | `209,426` | **`25,202`** | **`-87.97%`** |
| Lambda GB-Seconds | `36.7620` | **`13.6749`** | **`-62.80%`** |
| Cache Hits / Escalations / Fallbacks | `0 / 0 / 0` | **`15 / 1 / 0`** | `+15 cache hits` |

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
     │ DynamoDB, 24h   │      │  keywords + size  │     │  Nova Lite / Pro  │
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
    "model_id": "apac.amazon.nova-pro-v1:0",
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
`route_decision` ∈ `single_heavy, cache_hit, nova_lite, escalated_pro, direct_pro, fallback_pro`.

`GET /health` is a dependency-free liveness probe. `GET /stats` scans
`TicketsTable` and returns severity/category rollups, p95 latency, spend and
cache/escalation counts.

## Deploy

Prerequisites: AWS CLI v2 with credentials, SAM CLI, and Bedrock model access to
`apac.amazon.nova-pro-v1:0` (and `apac.amazon.nova-lite-v1:0` for v2) in `ap-southeast-2`.

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

## Benchmark

`eval/dataset_100_tickets.json` holds 100 hand-labelled tickets: 55 routine
tier-1, 20 repeat/alert-burst tickets (five canonical incidents repeated four
times with different IDs, timestamps and whitespace) and 25 complex tier-2 /
critical tickets, including 11 ground-truth P1s.

```powershell
python eval/run_benchmark.py --validate-only
python eval/run_benchmark.py --v1-url $V1 --v2-url $V2 --concurrency 2 --pacing 2.5
```

The runner replays both stacks with concurrency capped at 2 (and pacing ≥ 1.5 s) and
reports accuracy, severity/category accuracy, P1 recall and precision, p95
latency, exact spend, cost per successful ticket, GB-seconds, frontier tokens,
cache/escalation/fallback counts, a v1↔v2 disagreement diff and regression list.
A non-200 or off-contract response counts as a miss — it is never dropped.

The five repeat groups collapse to five normalised cache keys, so a cold run
produces 15 real cache hits out of 20 repeat tickets. Stage 1's deterministic
complexity gate routes unambiguous active P1s (`CRITICAL_P1_SIGNALS` / multi-signal
outages) straight to Nova Pro in 1 hop (`direct_pro`), while routine tickets take
Nova Lite and borderline predictions escalate via the confidence/P1 guardrail.

## Live deck

```powershell
cd frontend
Copy-Item .env.example .env.local   # set VITE_V1_API_URL and VITE_V2_API_URL
npm install
npm run dev
```

The deck is a responsive dark obsidian glassmorphic viewport (`Dashboard`,
`Live Replay`, `WAR Audit`, `Settings`): stack health, `V2 Route Distribution`,
`v1-before` vs `v2-after` glass cards, `Live Telemetry` chart, `Efficiency & Recall`
radial ring, the 10K→5M monthly ROI slider, `WAR Maturity` summary, and the
Well-Architected 3D pipeline + delta trace. It talks to the same contract as the
benchmark and caps each stack at 2 in-flight requests.

## Well-Architected review

[docs/war-before.md](docs/war-before.md) is the baseline review: 47 in-scope
Best Practices across Sustainability (14) and Cost Optimization (33), acquired
from the live framework corpus at review time, with `path:line` evidence for
every finding. Headline gaps: 100% frontier routing (COST05-BP05), no repeat
cache (SUS03-BP01), fixed x86_64/512 MB (COST06-BP02), no request ceiling
(COST08-BP02) and a heavy model for every task class (SUS03-BP03).

## Local development

```powershell
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest          # 68 tests, no AWS calls
```

The Lambda handler is framework-free and covered with a fake Bedrock client, so
validation, telemetry, persistence-failure and model-output-recovery paths are
all tested offline. Architecture and trade-offs are in
[docs/architecture.md](docs/architecture.md).

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
- **Honest accounting.** An escalated request is billed as Lite + Pro tokens,
  not as Lite. Cost per *successful* ticket is the headline metric, not cost per
  request.
- **Least privilege.** The role can `InvokeModel` on exactly one inference
  profile and its foundation-model ARN, and can touch exactly one table.
- **No Docker.** Zero native wheels means `sam build` produces an arm64 zip
  anywhere, including Windows.

## Status

- `v1-before` implemented and unit-tested; template validates and builds.
- 100-ticket benchmark, async runner and baseline Well-Architected review are
  committed ([docs/war-before.md](docs/war-before.md)).
- The live deck typechecks and produces a production bundle
  (`frontend` → `npm run build`).
- `v2-after` is implemented on `feat/war-tiered-model-router`: fail-open TTL
  cache (`Decimal` serialization), 1-hop `CRITICAL_P1_SIGNALS` gate + confidence/P1
  guardrail on Nova Lite → Pro, arm64/256 MB, and API throttling. **68 tests**
  green; both `v1` and `v2` template profiles validate and build.
- Both stacks are deployed live in `ap-southeast-2` (`modelshield-v1` and
  `modelshield-v2`), with `eval/results/benchmark_report.json` showing **82.33%**
  cost/10K reduction, **12.28%** p95 latency reduction, **87.97%** frontier tokens
  avoided, **100%** P1 recall, and **15** live DynamoDB cache hits (`0` errors,
  `0` fallbacks).
