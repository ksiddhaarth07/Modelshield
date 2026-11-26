# Well-Architected Review: ModelShield (v2-after)

> **Classification: CONFIDENTIAL** — This report contains sensitive infrastructure details and unremediated findings. Restrict distribution to authorized personnel. Do not post to broadly visible channels or ticketing systems without explicit approval.

**Review type:** Pillar-scoped closed-loop re-review — **Sustainability** and **Cost Optimization** only (all other pillars out of scope).
**Baseline:** `docs/war-before.md` (v1-before), same frozen corpus, same 47 in-scope BPs.
**Code state:** branch `feat/war-tiered-model-router`, commit **`1c3219f`** ("feat(router): complexity-aware Nova routing and fail-open TTL cache"). Still **not deployed** — assessment is code/IaC only, so no runtime claim below is verified against AWS. **All files cited in this report are unmodified in the working tree relative to `1c3219f`.** A concurrent process outside this review modified other files in the working tree while it ran (`README.md`, `backend/src/prompts.py`, `eval/dataset_100_tickets.json`, `frontend/src/data/tickets.ts`, new `eval/run_local_live.py`); those changes are **not part of v2** and are disclosed in the working-tree note below rather than folded into the assessment.

---

## Coverage Audit

- **BPs evaluated: 47 / 47.** Applicable target for a pillar-scoped review = the frozen manifest filtered to the two requested pillars.
- **Corpus provenance:** **reused verbatim** from the v1-before run — `https://docs.aws.amazon.com/wellarchitected/latest/framework/toc-contents.json`, retrieved **2026-11-26T07:15:59Z**, method `https_toc_index`. The manifest re-validated `valid: true` with the identical 47 BP IDs (33 Cost optimization + 14 Sustainability) and 14 questions; the rebuilt ID set was machine-compared against the v1 ledger and is **identical, zero drift**.
- **Why the corpus was not re-enumerated:** the two reports must be directly comparable at BP granularity. Re-walking the framework could silently change the expected set mid-comparison, which the frozen-manifest design exists to prevent.
- **Live pages re-fetched this run: none.** This is a deliberate constraint of the closed-loop comparison, **not a retrieval failure**. The BP bodies that drive the flipped findings — COST05-BP02, COST06-BP03, COST08-BP02, SUS02-BP03, SUS03-BP03 — were retrieved and quoted during the v1 run (2026-11-26T07:16Z), so the guidance behind each flip is grounded in live text already in this review trail. No new "Cannot Determine" status was introduced for retrieval reasons.
- **Pillars:** 6 discovered, **2 in scope** · **Questions: 14** · **Best practices: 47**.
- **Status distribution (v1 → v2):**

| Status | v1 | v2 | Δ |
|--------|----|----|---|
| Implemented | 5 | **10** | +5 |
| Partially Implemented | 23 | 25 | +2 |
| Not Implemented | 14 | **7** | −7 |
| Not Applicable | 3 | 3 | 0 |
| Cannot Determine | 2 | 2 | 0 |

- **BPs whose status changed: 9** (every one traceable in `docs/war-diff.md`). Risk-bearing rows: 14 Medium, 18 Low, **0 High, 0 Critical**.

### Code and IaC examined this run

Changed at `1c3219f`: `backend/src/cache.py` (new, 130 lines), `backend/src/router.py` (new, 295), `backend/src/handler.py` (v2 delegation), `backend/src/bedrock_client.py` (per-client boto config), `infra/template.yaml` (conditions, cache table, arm64/256 MB, throttling, IAM), `backend/tests/test_cache.py` (new), `backend/tests/test_router.py` (new), `backend/tests/test_handler.py` (+40). Unchanged at `1c3219f` and re-read for dependency effects: `backend/src/schemas.py`, `backend/src/metrics.py`, `backend/src/storage.py`, `backend/requirements.txt`, `infra/samconfig.toml`, `eval/run_benchmark.py`. `backend/src/prompts.py` is **changed in the working tree only** — see the working-tree note below; no anchor in this report depends on it.

**Test evidence (executed):** `python -m pytest` in `backend/` → **58 passed in 0.37 s**, no AWS calls. This confirms the router's cache-hit, gate, Micro, escalation, fallback and fail-open paths (`test_router.py:103-264`), the cache's key normalisation and TTL behaviour (`test_cache.py:14-91`), and the v1/v2 handler split (`test_handler.py:174-213`). It does **not** confirm any deployed behaviour, cost saving, or latency number.

**Sanitisation:** no AWS account IDs, access keys, or real ARNs. The only ARN text in this report is the template's own generic CloudFormation pattern built from `${AWS::Region}` / `${AWS::AccountId}` pseudo-parameters (`infra/template.yaml:163-172`).

---

## Executive Summary

- **Date:** 2026-11-26
- **Workload:** ModelShield — serverless AI triage gateway (`POST /triage`, `GET /health`, `GET /stats`)
- **Business Criticality:** High (demo/hackathon workload; **no production SLA is asserted or inferred**)
- **Region:** us-east-1, single Region (`infra/samconfig.toml:8`, `:25`)
- **Lens Applied:** None (pillar-scoped)
- **Questions Assessed:** 14 / 14 · **Best Practices:** 47 / 47
- **Findings:** **0 Critical, 0 High**, 14 Medium, 18 Low (v1 was 0 / 9 / 10 / 18)
- **Overall Maturity:** **3 / 5** (v1: 2/5) — the inference path is now actively managed and instrumented; the *management* of cost and efficiency as an ongoing practice is still missing.
- **Pillar scores:** Cost optimization **2 → 3**, Sustainability **2 → 3**.

### The verdict in one paragraph

v2 fixes the four things that made v1 wasteful, and fixes them at the right layer. The dominant cost driver — "every ticket goes to the frontier model, forever" — is now a **four-stage router**: normalised-key cache, deterministic complexity gate, Nova Micro for routine traffic, and a confidence/P1 guardrail that escalates to Nova Pro (`backend/src/router.py:86-164`). Repeat work is genuinely reused: a normalised SHA-256 key strips ticket IDs, UUIDs, ISO timestamps, casing and whitespace (`backend/src/cache.py:50-61`) and a DynamoDB table with a 24-hour TTL (`infra/template.yaml:88-105`) serves hits at **$0 model cost** with `cache_hit` now a real measured value rather than the hardcoded `False` that v1 shipped (`handler.py:258`, `:300`). Compute moved to **arm64 at 256 MB** (`infra/template.yaml:117-122`) for an I/O-bound handler, and the edge finally has a **spend ceiling** — 25 req/s, burst 50 (`infra/template.yaml:60-64`). Escalations are billed honestly as Micro + Pro (`router.py:148-153`), which is the detail that separates this from a marketing benchmark. The result is 9 BP status flips, 7 fewer Not-Implemented BPs, and **no High findings left**.

**But 3/5, not 4/5, and that is the honest score.** Everything v2 fixed was a *code or IaC* change. Everything still open is a *practice*: no budget, no forecast, no spend alarm, no cost-allocation tags, no ticket TTL, no demand model, no five-component cost baseline, no review cadence (`COST01-BP01`, `COST02-BP01`, `COST02-BP03`, `COST03-BP03`, `COST05-BP02`, `COST08-BP01`, `COST09-BP01`). And the headline saving is still **unproven**: nothing is deployed, so the claimed 55–85% frontier-token reduction is a design expectation, not a measurement. The harness that would prove it exists and is unchanged (`eval/run_benchmark.py:306-356`), which is exactly why the next step is a run, not a rewrite.

### What v2 made worse (stated up front, not buried)

1. **Escalated and fallback tickets now cost more than v1.** A guarded escalation pays Micro **plus** Pro (`router.py:148-153`). At the README's own token counts (286 in / 114 out) that is ≈**+4.4%** per escalated ticket versus the single Pro call (Pro $0.0005936 vs Micro $0.0000260 from `bedrock_client.py:26-29`). The 10 P1s that Micro labels P1 and every Micro-error fallback land in this bucket.
2. **Tail latency rises on exactly the tickets that matter.** The escalation path is two *serial* model calls; the P1s and low-confidence tickets that take it roughly double their model time. A cache miss also adds one DynamoDB `GetItem` before any model call (`router.py:89`, `cache.py:95`).
3. **The 29 s timeout budget is now shared by up to two hops.** Micro allows 2 attempts × (2 s connect + 6 s read) ≈ 16 s and Pro 2 attempts × (2 s + 8 s) ≈ 20 s (`router.py:34-36`, `bedrock_client.py:103`, `template.yaml:39`). The pathological double-retry path is ≈**36 s > 29 s** — the per-attempt caps narrowed exposure without eliminating it.
4. **A cached P1 stays cached for 24 hours.** Escalated results are written through (`router.py:138-155` → `_store`), so an incident that worsens within the day but re-arrives with the same normalised text returns the earlier triage at $0. That is the price of the hit rate.
5. **The gate is weak, so most complex work pays Micro first.** It fires on only **1 of 100** benchmark tickets — verified offline by running `AdaptiveRouter._is_complex` over the current `eval/dataset_100_tickets.json`: exactly one trigger, `tkt-077`, which is itself a P1. The other 10 P1s reach Micro first and are caught by the P1 guardrail afterwards. Complex tickets that trip fewer than two keywords therefore pay a wasted Micro call before escalating.
6. **`ModelId` is now a misleading parameter in v2.** `samconfig.toml:50` still passes `ModelId=us.amazon.nova-pro-v1:0`, the template forwards it (`template.yaml:126`), and `/health` reports it (`handler.py:185`) — but the v2 router ignores it and hardcodes both models (`router.py:283-292`). Operationally, `/health` can describe a model the request path is not using.

None of these is a High finding on its own at demo scale, but they are real costs of the optimisation and belong in the record.

### Working-tree note — concurrent changes outside v2 (disclosed, not assessed as v2)

While this review ran, a process outside it modified files in the working tree that are **not part of commit `1c3219f`**. They are disclosed here so the evidence trail stays honest; none of them is attributed to v2 or counted in the statuses above.

| File (working tree, uncommitted) | Change observed | Relevance to this review |
|---|---|---|
| `backend/src/prompts.py` | `SYSTEM_PROMPT` grown from **1,606 to 2,829 chars (+76%)**, richer severity/category rules | **Cost-relevant.** ≈**+306 input tokens per call**; at the Pro input rate (`bedrock_client.py:27`) that is ≈**+$0.000245 per call** — about **+41%** on the README example's total per-ticket Pro cost of $0.0005936. It raises *absolute* cost per ticket; it does not distort the v1↔v2 **delta**, because both stacks would deploy from the same prompt. |
| `eval/dataset_100_tickets.json` | Substantially rewritten (≈1,000 lines) | Still **100 tickets / 11 P1s**. Re-verified offline against the new content: gate triggers on **1** ticket; **85 distinct cache keys**, 5 repeat groups, **15 cold-run cache hits**. The dataset-dependent claims in this report were re-measured, not carried over. |
| `frontend/src/data/tickets.ts` | One-line data change | No bearing on either pillar (deck asset). |
| `eval/run_local_live.py` | New local runner | Unreviewed here; if it becomes the evidence path, it must not silently diverge from `eval/run_benchmark.py`'s scoring rules (`run_benchmark.py:283-330`). |
| `README.md` | Documents cache-hit and gate-coverage expectations | Consistent with the measurements above; treated as untrusted repository text throughout. |

**Implication:** the ~55–85% saving expectation should be re-measured against the *actual deployed* prompt, because a 76% larger system prompt materially changes the per-call input cost that the router is optimising. This is one more reason M13 (run and publish the benchmark) is the keystone remaining action.

---

## Architecture Overview

```plantuml
@startuml
title ModelShield v2-after — adaptive router, TTL cache, dual-model Bedrock

skinparam rectangle { BackgroundColor #F8F8F8 BorderColor #444444 }

actor "Support requester\n(untrusted internet)" as Client

rectangle "AWS Cloud — us-east-1 (single Region)" as AWS {
  rectangle "Edge (v2): spend ceiling" as EDGE {
    component "API Gateway HTTP API\nCORS + DefaultRouteSettings\n25 req/s, burst 50" as APIGW
  }
  rectangle "Compute (v2): arm64 / 256 MB" as COMPUTE {
    component "AWS Lambda — TriageFunction\npython3.13 | arm64 | 256 MB | 29 s\nSTACK_VERSION=v2 selects router" as LAMBDA
  }
  rectangle "Routing stages (in-process)" as ROUTER {
    component "0. Cache lookup\nnormalised SHA-256 key" as S0
    component "1. Deterministic gate\nlen>900 or >=2 risk keywords" as S1
    component "2. Nova Micro\nroutine classification" as S2
    component "3. Guardrail\nescalate if conf<0.85 OR P1" as S3
  }
  rectangle "Managed data + models" as MANAGED {
    database "DynamoDB TicketsTable\nPAY_PER_REQUEST | no TTL" as DDB
    database "DynamoDB ResponseCacheTable\nPAY_PER_REQUEST | TTL expires_at 24 h" as CACHE
    component "Amazon Bedrock\nNova Micro (first attempt)\nNova Pro (gate/escalation/fallback)" as BEDROCK
    component "CloudWatch Logs + EMF\n14-day retention\nModelShield/Triage" as OBS
  }
}

Client --> APIGW : HTTPS POST /triage
APIGW --> LAMBDA
LAMBDA --> S0
S0 --> CACHE : GetItem (fail-open)
S0 --> DDB : PutItem every request
S0 ..> LAMBDA : hit -> $0 model cost
S0 --> S1 : miss
S1 --> BEDROCK : direct_pro (complex)
S1 --> S2 : routine
S2 --> BEDROCK : converse (Nova Micro)
S2 --> S3 : confidence / severity
S3 --> BEDROCK : escalate -> Nova Pro
S2 ..> BEDROCK : Micro error/invalid JSON -> Pro fallback
LAMBDA --> OBS : one EMF line/request\ncache|escalated|fallback counters

note bottom of S1
  Measured on the 100-ticket dataset: the gate fires on 1 ticket.
  10 of the 11 P1s reach Pro via the stage-3 guardrail, not the gate.
end note
note bottom of CACHE
  Fail-open by contract: a cache outage degrades to v1 behaviour
  (one full model call), never to a 5xx.
end note
@enduml
```

**Routing, precisely.** `AdaptiveRouter.route()` computes the normalised key (`router.py:87`), returns immediately on a valid cache hit at zero cost (`:89-105`), sends long/multi-signal tickets straight to Pro (`:107-117`), otherwise calls Nova Micro (`:121`), and escalates to Pro when `confidence < 0.85` **or** severity is `P1` (`:131-134`). Micro errors and invalid JSON fall back to Pro (`:123-129`, `:176-206`). Every outcome is written through to the cache (`:271-276`). The handler delegates only when `STACK_VERSION == "v2"` (`handler.py:139-140`, `:153-154`); the v1 path is byte-for-byte the old behaviour (`:156-174`), which is what makes the two stacks comparable.

**Accounting contract (important for interpreting the metrics).** On `escalated_pro` and `fallback_pro`, `input_tokens`/`output_tokens`/`estimated_cost_usd` are **sums across both calls**, while `frontier_tokens_used` counts **Pro tokens only** (`router.py:148-153`, `:200-204`). v1's invariant `input + output == frontier_tokens_used` therefore no longer holds on those routes. That is deliberate and honest, but any consumer that assumes the old identity will misread the dashboard.

---

## Pillar Scorecard

| Pillar | v1 | **v2** | Δ | Questions | Key Strength (v2) | Key Gap (v2) |
|--------|----|----|---|-----------|-------------------|--------------|
| **Cost optimization** | 2 | **3** | +1 | 10 / 10 | The dominant cost driver is now actively managed: cache at $0 hits, Micro for routine traffic, confidence/P1 escalation, arm64/256 MB, and a 25 r/s spend ceiling — all with per-route cost telemetry that bills escalations honestly as Micro + Pro. | Cost is still *measured*, not *governed*: no budget, no forecast, no spend alarm, no cost-allocation tag, no five-component baseline, no demand model, no review cadence. And the saving is unmeasured because nothing is deployed. |
| **Sustainability** | 2 | **3** | +1 | 4 / 4 | Resource use now tracks business need for routine traffic; repeat work is reused instead of re-inferred; Graviton replaces x86_64; zero-idle elasticity is preserved. | Efficiency is not *measured* as efficiency (no RUE per business value, no environmental data), the complexity gate is imprecise enough that 10 P1s still double-infer, and ticket data still has no retention bound. |

**Why not 4/5.** A 4 requires the optimisation to be *measured and governed*. v2 built the levers but not the measurement loop (no deployment, no RUE, no budget) and not the governance (no tags, no alarms). **Why not 2/5.** The three largest levers from the v1 review are now implemented in code with fail-open semantics and tests — that is a genuine, evidenced change, not a claim.

---

## Per-Question Assessment

| ID | Question (live TOC label) | v1 | v2 | Risk | Key v2 Evidence |
|----|---------------------------|----|----|------|-----------------|
| COST01 | Practice cloud financial management | Partially Implemented | Partially Implemented | Medium | Route cost measured per request (`router.py:244`); still no budget, forecast or target anywhere in `template.yaml:41-310`. |
| COST02 | Monitor cost and usage | Partially Implemented | Partially Implemented | Medium | Dashboard + `StackVersion` EMF dimension (`metrics.py:49`); **zero tags** and no alarm/anomaly detection. |
| COST03 | Manage the lifecycle of resources | Partially Implemented | Partially Implemented | Medium | Cache table has a real TTL (`template.yaml:100-102`); `TicketsTable` still has none (`:69-82`). |
| COST04 | Plan for data transfer | Partially Implemented | Partially Implemented | Low | Single Region, no VPC/NAT (`samconfig.toml:8`); still no data-transfer model. |
| COST05 | Evaluate cost when selecting services | Partially Implemented | Partially Implemented | Medium | Value-driven model selection now real (`router.py:107-164`); TCO and component inventory still absent. |
| COST06 | Select the correct resource type, size, and number | Partially Implemented | Partially Implemented | Medium | arm64/256 MB with stated rationale (`template.yaml:117-122`, `:108-110`); not yet validated by measurement. |
| COST07 | Select the best pricing model | Partially Implemented | Partially Implemented | Low | On-demand everywhere (`template.yaml:73`, `:93`); reasoning still undocumented. |
| COST08 | Manage demand and supply resources | Partially Implemented | Partially Implemented | Medium | Throttle now bounds demand (`template.yaml:60-64`); no demand analysis to size it (COST08-BP01). |
| COST09 | Optimize over time | Partially Implemented | Partially Implemented | Low | Harness exists (`run_benchmark.py:333-356`); no cadence, owner or history. |
| COST10 | Automate operations | Partially Implemented | **Implemented** | — | Fully codified ops plus efficiency automation now in the request path (`router.py`, `cache.py`). |
| SUS01 | Measure and monitor sustainability | Partially Implemented | Partially Implemented | Low | Real cache/escalation/fallback counters (`handler.py:258-263`); no RUE per business value, no carbon data. |
| SUS02 | Optimize resource provisioning | Partially Implemented | Partially Implemented | Medium | Routine→Micro, complex→Pro, 256 MB (`router.py:107-164`, `template.yaml:122`); gate imprecision and double inference on P1s. |
| SUS03 | Enhance workload efficiency | **Not Implemented** | Partially Implemented | Medium | Cache + tiering + Graviton all implemented; efficiency gain still unmeasured and gate coverage weak. |
| SUS04 | Optimize data and processing | Partially Implemented | Partially Implemented | Medium | New cache data is TTL-bounded (`template.yaml:100-102`); ticket records still unbounded (`:69-82`). |

---

## Full BP Ledger

One row per Best Practice in the frozen manifest (47 rows: 33 Cost optimization + 14 Sustainability). `v1` and `v2` are the assessed statuses; `Risk` is the **v2** residual risk. Evidence provenance: `[code]` = Observed in code/IaC; `[scope]` = Not observed within declared scope.

### Cost optimization (33 best practices)

| BP ID | Pillar | v1 | v2 | Risk | Evidence | Gap / Recommendation |
|-------|--------|----|----|------|----------|----------------------|
| COST01-BP01 | Cost | Not Implemented | Not Implemented | Medium | No `AWS::Budgets::Budget`, forecast or spend alarm (`infra/template.yaml:41-310`); the new throttle (`:60-64`) bounds runaway spend but does not observe it `[code]` | Add a budget with a forecasted-spend alert plus an estimated-charges alarm. Risk drops Medium (was High) because the throttle now caps the blast radius. |
| COST01-BP02 | Cost | Partially Implemented | Partially Implemented | Low | Exact per-request USD cost (`bedrock_client.py:74-81`) and per-route cost split (`router.py:94-104`, `:244`) `[code]` | Still no numeric target; define a cost-per-10k-tickets goal and alarm on it. |
| COST01-BP03 | Cost | Partially Implemented | Partially Implemented | Low | `IsV2` conditions (`template.yaml:33-34`) and two samconfig profiles (`samconfig.toml:24-50`) separate the phases `[code]` | No per-phase cost tracking or stack retirement policy. |
| COST01-BP04 | Cost | Cannot Determine | Cannot Determine | — | Two-value model allow-list is the only signal (`template.yaml:21-23`) `[scope]` | Needs owner interview on release-tracking cadence. |
| COST02-BP01 | Cost | Not Implemented | Not Implemented | Medium | Still **zero `Tags:` keys** on any of the 6 resources (`infra/template.yaml:41-310`) `[code]` | Add a `Globals` `Tags` block (`Environment`, `Workload`, `StackVersion`, `Owner`) — now urgent because v1 and v2 must be attributed separately. |
| COST02-BP02 | Cost | Partially Implemented | Partially Implemented | Low | `StackVersion` EMF dimension (`metrics.py:49`); cost/success computed in the harness (`run_benchmark.py:322`) `[code]` | Surface cost per successful ticket in `/stats` and the dashboard. |
| COST02-BP03 | Cost | Partially Implemented | Partially Implemented | Medium | Dashboard only (`infra/template.yaml:203-284`); no alarm, Budgets or Cost Anomaly Detection `[code]` | Add spend alarm + anomaly detector on a channel a human reads. |
| COST03-BP01 | Cost | Partially Implemented | Partially Implemented | Low | One template, stable logical names, six outputs (`infra/template.yaml:286-310`) `[code]` | No owner/expiry metadata per resource. |
| COST03-BP02 | Cost | Partially Implemented | Partially Implemented | Low | Cache table lifecycle is TTL-driven (`template.yaml:100-102`); `DeletionProtectionEnabled: false` on both tables (`:82`, `:105`) `[code]` | Set a retirement date for the v1 stack; enable deletion protection before any prod use. |
| COST03-BP03 | Cost | Partially Implemented | Partially Implemented | Medium | Cache entries expire at 24 h (`cache.py:27`, `:123`; `template.yaml:100-102`); `TicketsTable` still has **no TTL** (`:69-82`) `[code]` | Add a TTL attribute for demo ticket records; the cache half of this BP is now genuinely done. |
| COST04-BP01 | Cost | Partially Implemented | Partially Implemented | Low | Single Region, no VPC/NAT/endpoints (`infra/samconfig.toml:8`) `[code]` | Record the near-zero data-transfer reasoning. |
| COST04-BP02 | Cost | Not Implemented | Not Implemented | Low | No data-transfer model in `infra/`, `docs/` or `eval/` `[code]` | One-page byte model at projected volume. |
| COST04-BP03 | Cost | Partially Implemented | Partially Implemented | Low | Bounded request payloads (`backend/src/schemas.py:18-24`) and a 400-token output cap (`bedrock_client.py:117`) `[code]` | Validate response size against consumer need. |
| COST05-BP01 | Cost | Partially Implemented | Partially Implemented | Low | Cost is a stated design driver (`infra/template.yaml:31`; `README.md:8-12`) `[code]` | Write "$X per 10k tickets" as an explicit requirement. |
| COST05-BP02 | Cost | Partially Implemented | Partially Implemented | Medium | Bedrock cost is exact (`bedrock_client.py:74-81`) and now **split by route** — cache $0, Micro, escalated Micro+Pro, fallback (`router.py:94-104`, `:142-153`, `:194-204`) `[code]` | The *alternatives are now costed*, which was the core v1 gap; the five-component baseline (API GW, Lambda, DynamoDB, Logs) still does not exist. Risk High → Medium. |
| COST05-BP03 | Cost | Not Implemented | Not Implemented | Medium | No TCO artefact; only per-token rates (`bedrock_client.py:25-29`) `[code]` | Per-component TCO once the C5 baseline exists. |
| COST05-BP04 | Cost | Implemented | Implemented | — | Zero third-party runtime dependencies — `requirements.txt` intentionally empty `[code]` | Keep the empty-dependency invariant. |
| COST05-BP05 | Cost | Partially Implemented | **Implemented** | — | Model is selected by complexity and confidence: gate (`router.py:248-252`), routine→Micro (`:119-129`), escalate on conf<0.85 or P1 (`:131-155`); Micro is genuinely invoked and permitted in IAM (`template.yaml:166-172`) `[code]` | Done. Residual (tracked under SUS02-BP03): gate precision, not the principle. |
| COST05-BP06 | Cost | Partially Implemented | Partially Implemented | Low | Repeatable v1↔v2 harness (`eval/run_benchmark.py:306-356`) unchanged `[code]` | Run it, then put it on a cadence with retained history. |
| COST06-BP01 | Cost | Partially Implemented | Partially Implemented | Medium | Per-token model plus a per-route cost model (`bedrock_client.py:26-29`; `router.py:244`) `[code]` | No end-to-end per-ticket cost model across all five components. |
| COST06-BP02 | Cost | Not Implemented | **Partially Implemented** | Medium | `Architectures: !If [IsV2, arm64, x86_64]` and `MemorySize: !If [IsV2, 256, 512]` (`infra/template.yaml:117-122`), rationale at `:108-110`, `ARCHITECTURE` env at `:133-136` `[code]` | The choice is now *reasoned* (I/O-bound handler, zero native wheels) but **not yet data-validated** — no deployment, so no GB-seconds/p95 evidence exists. Partial, not Implemented, for that reason. |
| COST06-BP03 | Cost | Not Implemented | Not Implemented | Medium | Sizing is a static `!If` (`template.yaml:117-122`); no Compute Optimizer automation rules or Power Tuning artefact `[code]` | After COST06-BP02 is measured, codify the result; consider Compute Optimizer automation for the function. |
| COST06-BP04 | Cost | Not Applicable | Not Applicable | — | No shared self-managed resource to consolidate `[code]` | Revisit only if a shared VPC or cache cluster appears. |
| COST07-BP01 | Cost | Partially Implemented | Partially Implemented | Low | On-demand everywhere (`template.yaml:73`, `:93`); no commitments or provisioned concurrency `[code]` | Document why commitments do not fit spiky demo traffic. |
| COST07-BP02 | Cost | Partially Implemented | Partially Implemented | Low | us-east-1 fixed (`infra/samconfig.toml:8`, `:25`) for model availability (`README.md:111-112`) `[code]` | Note the cost trade-off in the design doc. |
| COST07-BP03 | Cost | Not Applicable | Not Applicable | — | No third-party agreements `[code]` | Revisit if a managed vector store or SaaS is added. |
| COST08-BP01 | Cost | Not Implemented | Not Implemented | Medium | No demand analysis; `--concurrency 4` (`run_benchmark.py:520`) is a harness limit, not a traffic model `[code]` | Model peak rate, rate of change and required response time — then confirm or revise the throttle numbers. |
| COST08-BP02 | Cost | Not Implemented | **Implemented** | — | `DefaultRouteSettings` with `ThrottlingBurstLimit: 50` / `ThrottlingRateLimit: 25` under `IsV2` (`infra/template.yaml:60-64`), flagged in the comment at `:43-45` `[code]` | Done at the edge. Optional second ceiling: `ReservedConcurrentExecutions`, since Lambda concurrency is still unbounded (`:111-136`). |
| COST08-BP03 | Cost | Implemented | Implemented | — | Lambda + HTTP API + two `PAY_PER_REQUEST` tables, no provisioned capacity (`template.yaml:73`, `:93`) `[code]` | Keep. |
| COST09-BP01 | Cost | Not Implemented | Not Implemented | Low | No review cadence, owner or cost-review doc; harness must be invoked by hand (`run_benchmark.py:514-525`) `[code]` | Monthly cost review against the dashboard with a named owner. |
| COST09-BP02 | Cost | Partially Implemented | Partially Implemented | Low | Deltas computed by the harness (`run_benchmark.py:333-356`) `[code]` | Not scheduled; no cost-regression gate in CI. |
| COST10-BP01 | Cost | Implemented | Implemented | — | One SAM template, scripted build/deploy (`deploy.ps1:9-13`), profiles (`samconfig.toml:24-50`) `[code]` | Add CI so automation does not depend on a workstation. |
| COST10-BP02 | Cost | Partially Implemented | **Implemented** | — | Managed Bedrock used *efficiently*, not just used: cache short-circuits inference (`router.py:86-105`) and routine traffic takes the cheap managed model (`:119-164`); IAM scoped to the two profiles (`template.yaml:157-172`) `[code]` | Done. Maintain the efficiency as new routes are added. |

### Sustainability (14 best practices)

| BP ID | Pillar | v1 | v2 | Risk | Evidence | Gap / Recommendation |
|-------|--------|----|----|------|----------|----------------------|
| SUS01-BP01 | Sustainability | Partially Implemented | Partially Implemented | Low | Per-request GB-seconds/tokens (`handler.py:250-252`, `:263`) plus a route-level split (`router.py:243`) `[code]` | No resource-usage-efficiency metric normalised per business value (tokens and GB-s per triaged ticket) on the dashboard. |
| SUS01-BP02 | Sustainability | Partially Implemented | Partially Implemented | Low | Five-widget dashboard (`infra/template.yaml:203-284`) now fed by real cache/escalation/fallback data `[code]` | Still **no environmental-impact data** — no carbon or proxy metric. |
| SUS01-BP03 | Sustainability | Cannot Determine | Cannot Determine | — | Region fixed at us-east-1 (`samconfig.toml:8`), justified by model access (`README.md:111-112`) `[scope]` | Business decision: document whether this meets the org's sustainability goals. |
| SUS02-BP01 | Sustainability | Implemented | Implemented | — | Scales to zero; two `PAY_PER_REQUEST` tables; no provisioned concurrency (`template.yaml:73`, `:93`, `:111-136`) `[code]` | Keep. |
| SUS02-BP02 | Sustainability | Partially Implemented | Partially Implemented | Low | Tests are fully offline and now cover cache/router (`test_cache.py`, `test_router.py`; 58 passed) — no provisioned test infra `[code]` | Two live stacks still run side by side for comparison (`samconfig.toml:24-50`); set a teardown date. |
| SUS02-BP03 | Sustainability | Not Implemented | **Partially Implemented** | Medium | Routine traffic takes Micro, complex takes Pro (`router.py:107-164`); 256 MB (`template.yaml:122`); but the gate fires on **1/100** tickets and 10 P1s still pay Micro before Pro (`:131-155`) `[code]` | Resource use now *tracks* need, but the gate's coverage is weak. Tighten the gate (or accept the guardrail-only design and document it) and measure tokens/GB-s per ticket. |
| SUS02-BP04 | Sustainability | Not Applicable | Not Applicable | — | No steady-state baseload; demo traffic is bursty `[code]` | Revisit at production volume. |
| SUS03-BP01 | Sustainability | Not Implemented | **Implemented** | — | Normalised SHA-256 key with ticket-ID/UUID/timestamp/case/whitespace stripping (`cache.py:31-61`), fail-open read (`:91-112`), 24 h TTL write (`:114-130`), TTL table (`template.yaml:88-105`), hit path at $0 (`router.py:86-105`), real `cache_hit` telemetry (`handler.py:258`, `:300`) `[code]` | Done. Residual: the cache **policy** (24 h TTL, what may be cached, P1 staleness) is not documented — see Medium M-13. |
| SUS03-BP02 | Sustainability | Not Implemented | **Partially Implemented** | Medium | The route throttle flattens peaks (`template.yaml:60-64`) and repeat bursts are absorbed by the cache (`cache.py`, `router.py:86-105`) `[code]` | No buffer/queue: bursts above 25 r/s are rejected rather than absorbed. Add SQS only if the demand model says they must be absorbed. |
| SUS03-BP03 | Sustainability | Not Implemented | **Partially Implemented** | Medium | Lightest-adequate tier per request: deterministic gate (`router.py:38-53`, `:248-252`), Micro for routine (`:119-129`), Pro only for complex/escalated (`:107-117`, `:135-136`) `[code]` | Implemented as a mechanism, but 10 P1s are inferred twice (Micro then Pro) and the gate is imprecise, so the *efficiency* claim is unproven. Measure the token/GB-s delta before calling it done. |
| SUS03-BP04 | Sustainability | Not Implemented | **Implemented** | — | `arm64` under `IsV2` (`infra/template.yaml:117-121`), `ARCHITECTURE: arm64` (`:133-136`), and nothing blocks it — zero native wheels (`backend/requirements.txt:1-6`, `samconfig.toml:4-5`) `[code]` | Done. Residual: arm64 cold-start risk is unmeasured (see trade-offs). |
| SUS04-BP01 | Sustainability | Partially Implemented | Partially Implemented | Medium | New cache data is TTL-bounded (`template.yaml:100-102`, `cache.py:27`); ticket records still retain full `draft_reply` + telemetry with no TTL (`template.yaml:69-82`), and up to 8,000 chars of body go to the model (`schemas.py:21`) `[code]` | Add a TTL to `TicketsTable`; consider trimming the body where the decision does not need it. |
| SUS04-BP02 | Sustainability | Partially Implemented | Partially Implemented | Low | Compact JSON (`handler.py:66`), single-line EMF (`metrics.py:66-67`), zero-dependency bundle `[code]` | Document why these payload sizes need no compression. |
| SUS04-BP03 | Sustainability | Implemented | Implemented | — | One cache `GetItem`, one bounded 2-hop escalation path, one single-item write — no chatty fan-out (`router.py:86-105`, `:131-136`; `handler.py:287`) `[code]` | Keep; watch the added second hop (see trade-offs). |

**Ledger verification:** 33 + 14 = **47** rows; distinct BP IDs = 47; identical to the frozen manifest and to the v1 ledger (machine-checked, zero drift). Status tallies: 10 Implemented, 25 Partially Implemented, 7 Not Implemented, 3 N/A, 2 Cannot Determine = 47.

---

## Delta Analysis — what flipped and what did not

**Nine BP statuses changed.** All nine are traced to a specific commit and evidence in `docs/war-diff.md`; summarised here:

| BP ID | v1 → v2 | What actually changed |
|-------|---------|-----------------------|
| COST05-BP05 | Partially Implemented → **Implemented** | Model choice is now driven by ticket complexity and confidence, not a constant. |
| COST06-BP02 | Not Implemented → **Partially Implemented** | arm64/256 MB with a stated rationale; awaiting measurement to close the last step. |
| COST08-BP02 | Not Implemented → **Implemented** | 25 r/s / burst 50 spend ceiling at the edge, v2 only. |
| COST10-BP02 | Partially Implemented → **Implemented** | Managed GenAI is now used *efficiently* (cache + tiering), not merely used. |
| SUS02-BP03 | Not Implemented → **Partially Implemented** | Routine work runs on the cheaper model at smaller memory; gate coverage still weak. |
| SUS03-BP01 | Not Implemented → **Implemented** | Repeat requests are reused via a normalised-key TTL cache with real hit telemetry. |
| SUS03-BP02 | Not Implemented → **Partially Implemented** | Peaks are flattened by the throttle and repeat bursts absorbed by the cache; no buffer. |
| SUS03-BP03 | Not Implemented → **Partially Implemented** | Lightest-adequate compute per request implemented; efficiency unmeasured, P1s double-infer. |
| SUS03-BP04 | Not Implemented → **Implemented** | Graviton/arm64 replaces x86_64. |

**Why the other 38 stayed put — the honest part.** They did not move because v2 is a *code* change and they are *practice* changes:

- **Seven BPs are still Not Implemented** — and none of them is code: budget/forecast (`COST01-BP01`), cost-allocation tags (`COST02-BP01`), data-transfer model (`COST04-BP02`), per-component TCO (`COST05-BP03`), automated right-sizing (`COST06-BP03`), demand analysis (`COST08-BP01`), review cadence (`COST09-BP01`). A template change could fix three of these cheaply (budget, tags, and half of the review cadence); the rest need a decision, not a diff.
- **Ticket retention did not move** (`COST03-BP03`, `SUS04-BP01`): the new cache table has a TTL, but `TicketsTable` still has none — v2 added a second bounded store while leaving the unbounded one in place.
- **Measurement gaps did not move** (`SUS01-BP01`, `SUS01-BP02`): the dashboard now displays *real* cache/escalation/fallback values, which is a genuine improvement in data quality, but no RUE metric and no environmental data were added, so the BP is still Partial.
- **Two BPs remain Cannot Determine** (`COST01-BP04`, `SUS01-BP03`): organisational decisions, unchanged.

### Risk movement

| BP ID | v1 risk | v2 risk | Why |
|-------|---------|---------|-----|
| COST01-BP01 | High | **Medium** | The throttle caps the blast radius of a spend spike; the missing budget/alarm is now a governance gap rather than an open-ended exposure. |
| COST05-BP02 | High | **Medium** | The alternatives (Micro, cache, escalation) are now costed per route, so the analysis no longer ignores its own subject. |
| COST06-BP02 | High | **Medium** | The shape is fixed and reasoned; only validation is outstanding. |
| SUS02-BP03 | High | **Medium** | Mismatch substantially reduced; residual is gate imprecision. |
| SUS03-BP02 | High | **Medium** | Peaks are bounded at the edge. |
| SUS03-BP03 | High | **Medium** | Tiering exists; residual is measurement and double inference. |
| COST05-BP05, COST08-BP02, SUS03-BP01 | High | — | Closed. |

Net: **9 High → 0 High; 0 Critical → 0 Critical.** Nothing in v2 is rated High because every remaining gap is either bounded (throttle, cache, TTL) or a governance/measurement omission whose worst case at demo scale is a missed optimisation rather than an uncontrolled spend event.

---

## Critical and High Risk Findings

**No Critical and no High findings remain.** This is a genuine change in risk posture, not a relaxation of standard:

- The three highest-leverage v1 findings are **closed in code** — unlimited frontier inference (`COST05-BP05`), no reuse of repeat work (`SUS03-BP01`), and no spend ceiling (`COST08-BP02`).
- The three that were rated High largely *because they compounded* those three (`COST01-BP01`, `COST05-BP02`, `SUS03-BP02`) drop to Medium once the compounding path is cut.
- The two that remain only partly addressed (`COST06-BP02`, `SUS02-BP03`) are capped at Medium because the residual is a *measurement* gap, not an uncontrolled behaviour.

What would push something back to High: deploying v2 **without** the budget alarm while traffic is unknown (unbounded *unobserved* spend under a 25 r/s ceiling is ≈$50+/hour at Pro rates), or discovering that the guardrail suppresses P1 recall — which cannot be known until the benchmark runs.

---

## Medium Risk Findings

| ID | BP ID | Pillar | Title | v2 Evidence | Impact × Likelihood | Recommendation |
|----|-------|--------|-------|-------------|---------------------|----------------|
| M1 | COST01-BP01 | Cost | No budget, forecast or spend alarm | `infra/template.yaml:41-310` (no `AWS::Budgets::Budget`, no `AWS::CloudWatch::Alarm`) | Moderate × Medium | Budget + forecasted-spend alert + estimated-charges alarm. Cheapest remaining high-value change. |
| M2 | COST02-BP01 | Cost | No cost-allocation tags | `infra/template.yaml:41-310` (no `Tags:`) | Moderate × Medium | `Globals` `Tags` block, including `StackVersion`, so v1 and v2 spend separate cleanly. |
| M3 | COST02-BP03 | Cost | Monitoring is passive | `infra/template.yaml:203-284` (dashboard only) | Moderate × Medium | Spend alarm + Cost Anomaly Detection. |
| M4 | COST03-BP03 | Cost | Tickets retain data forever | `infra/template.yaml:69-82` (no TTL on `TicketsTable`; the cache at `:100-102` does have one) | Moderate × Medium | TTL attribute on ticket records; keep the cache TTL as-is. |
| M5 | COST05-BP02 | Cost | No five-component cost baseline | `bedrock_client.py:74-81` + `router.py:244` cover Bedrock only | Moderate × Medium | Instrument API GW, Lambda, DynamoDB, Logs alongside Bedrock for one 100-ticket run. |
| M6 | COST05-BP03 | Cost | No per-component TCO | `bedrock_client.py:25-29` (rates only) | Moderate × Low | One-page TCO once M5 exists. |
| M7 | COST06-BP01 | Cost | No end-to-end cost model | Bedrock-only pricing; no per-ticket total | Moderate × Medium | Model per-ticket total and at projected volume. |
| M8 | COST06-BP02 | Cost | Right-sizing not yet data-validated | `infra/template.yaml:117-122` (reasoned, unmeasured) | Moderate × Medium | Run the benchmark; record measured GB-s and p95 next to the constant. |
| M9 | COST06-BP03 | Cost | No automated right-sizing loop | Static `!If` sizing (`template.yaml:117-122`) | Minor × High | Compute Optimizer automation rules once the size is measured. |
| M10 | COST08-BP01 | Cost | Throttle numbers not derived from a demand model | `infra/template.yaml:60-64`; `run_benchmark.py:520` is a harness limit | Moderate × Medium | Demand model; confirm or revise 25/50. |
| M11 | SUS02-BP03 | Sustainability | Gate coverage is weak; P1s double-infer | `router.py:248-252` (gate), `:131-155` (escalation) — 1/100 gate hits, 10 P1s escalated | Moderate × Medium | Tighten the gate or document guardrail-only routing; measure tokens per ticket. |
| M12 | SUS03-BP02 | Sustainability | No buffer for bursts above the ceiling | `infra/template.yaml:60-64` rejects; no queue | Moderate × Medium | SQS buffer only if the demand model shows bursts that must be absorbed. |
| M13 | SUS03-BP03 | Sustainability | Efficiency gain unproven | `router.py:107-164` implements tiering; no measured delta | Moderate × Medium | Run the v1↔v2 benchmark; publish route distribution and token/GB-s reduction. |
| M14 | SUS04-BP01 | Sustainability | Ticket data and prompt body unbounded | `template.yaml:69-82` (no TTL), `schemas.py:21` (8,000-char body) | Moderate × Medium | TTL tickets; trim the body where possible. |

---

## Low Risk Findings

| ID | BP ID | Pillar | Title | Recommendation |
|----|-------|--------|-------|----------------|
| L1 | COST01-BP02 | Cost | No cost goal or target | Define cost-per-10k target and alarm (pairs with M1). |
| L2 | COST01-BP03 | Cost | No per-phase cost tracking | Split spend by `StackVersion` tag once M2 lands. |
| L3 | COST02-BP02 | Cost | Cost-per-outcome only in the harness | Surface cost per successful ticket in `/stats`. |
| L4 | COST03-BP01 | Cost | No ownership/expiry metadata | Tag owner and expiry; list in outputs. |
| L5 | COST03-BP02 | Cost | Resource lifecycle unbounded | Teardown date for the v1 stack; deletion protection before prod. |
| L6 | COST04-BP01 | Cost | Data-transfer cost undocumented | Record the near-zero-transfer reasoning. |
| L7 | COST04-BP02 | Cost | No data-transfer model | One-page byte model at projected volume. |
| L8 | COST04-BP03 | Cost | Payload caps incidental | Validate response size against consumer need. |
| L9 | COST05-BP01 | Cost | No testable cost requirement | Write "$X per 10k tickets". |
| L10 | COST05-BP06 | Cost | Analysis not on a cadence | Monthly harness run with retained history. |
| L11 | COST07-BP01 | Cost | Pricing rationale undocumented | Record why on-demand fits spiky demo traffic. |
| L12 | COST07-BP02 | Cost | Region chosen for availability, not cost | Note the trade-off in the design doc. |
| L13 | COST09-BP01 | Cost | No review process or owner | Monthly cost review with a named owner. |
| L14 | COST09-BP02 | Cost | Optimisation vehicle not scheduled | Schedule the benchmark; gate on cost regressions. |
| L15 | SUS01-BP01 | Sustainability | No RUE per business value | Add tokens-per-ticket and GB-s-per-ticket widgets. |
| L16 | SUS01-BP02 | Sustainability | No environmental-impact data | Add Sustainability proxy metrics. |
| L17 | SUS02-BP02 | Sustainability | Two stacks kept alive | Teardown date for the baseline after measurement. |
| L18 | SUS04-BP02 | Sustainability | Formats chosen by convention | Document why compression is unnecessary at these sizes. |

## Cannot Determine

| ID | BP ID | Pillar | Title | What would resolve it |
|----|-------|--------|-------|-----------------------|
| C1 | COST01-BP04 | Cost | Keep up-to-date with new service releases | Owner interview on the model/service review cadence. The two-value allow-list (`template.yaml:21-23`) shows awareness, not process. |
| C2 | SUS01-BP03 | Sustainability | Select Regions that align to sustainability goals | Business decision on us-east-1 (`samconfig.toml:8`); the repo justifies the Region by model availability (`README.md:111-112`), not carbon intensity. |

---

## Cross-Pillar Trade-Offs

| Conflict | Tension | v2 resolution (accepted or open) |
|----------|---------|----------------------------------|
| **Cost ↔ Accuracy (cache)** | A 24 h cached triage is free but stale; a cached P1 could describe an incident that has since worsened. | **Accepted deliberately** for demo traffic, and the hit path is fail-open. Residual risk recorded as M13/SUS03-BP01 policy note: document what may be cached and consider bypassing the cache for `P1` results. |
| **Cost ↔ Latency (escalation)** | Escalating after Micro doubles model time for the tickets that matter most. | **Accepted**: correctness on P1s outranks tail latency, and the guardrail is the mechanism that protects P1 recall. Unmeasured until the benchmark runs (M13). |
| **Cost ↔ Reliability (throttle)** | 25 r/s protects spend but rejects legitimate bursts. | **Accepted** with a documented ceiling; revisit against M10's demand model. Note the throttle does not bound **cost per request**, only request rate. |
| **Sustainability ↔ Performance (arm64)** | Graviton may raise cold-start on a 256 MB function. | **Accepted as unverified**: the handler is I/O-bound (`template.yaml:108-110`), so the expected effect is small — but no measurement exists. Validate p95 in the same run that validates M8. |
| **Reliability ↔ all (timeout budget)** | Two hops × two attempts can exceed the 29 s Lambda timeout. | **Open.** `router.py:34-36` narrows per-attempt exposure, but ≈16 s (Micro) + ≈20 s (Pro) > 29 s. Consider capping total attempts across the pair or lowering the Pro read timeout. |
| **Cost ↔ Observability (telemetry identity)** | Escalations report summed input/output tokens but Pro-only frontier tokens. | **Accepted and documented** (`router.py:148-153`): honest billing beats a flattering metric. Consumers must not assume the v1 identity `input + output == frontier_tokens`. |
| **Security ↔ Cost (out of scope)** | The `/triage` route is still unauthenticated and unthrottled per-client; the throttle is global. | **Open, flagged only.** Security is out of scope; note that any auth/authorisation work will also bound the remaining cost exposure. |

---

## Prioritize Improvements — Eisenhower Matrix

```
        HIGH IMPORTANCE
             │
   ┌─────────┼─────────┐
   │  DO     │  PLAN   │
   │  FIRST  │         │
   │ M1 M2   │ M4 M5   │
   │ M3      │ M7 M8   │
   │ L5      │ M10 M11 │
   │         │ M12 M13 │
───┼─────────┼─────────┼───
   │         │         │
   │DELEGATE │  DEFER  │
   │ L2 L3   │ M6 M9   │
   │ L9 L13  │ L7 L8   │
   │ L15 L17 │ L16     │
   └─────────┼─────────┘
             │
        LOW IMPORTANCE
   LOW EFFORT    HIGH EFFORT
```

| Quadrant | Action | Findings |
|----------|--------|----------|
| **Do First** (High importance, low effort) | Implement immediately | **M1** (budget + forecast + spend alarm), **M2** (cost-allocation tags), **M3** (anomaly detection), **L5** (v1 teardown date) |
| **Plan** (High importance, high effort) | Schedule, break into phases | **M13** (run and publish the v1↔v2 benchmark — this is the keystone: it validates M8, M11 and the 55–85% claim), **M5** (five-component baseline), **M4** (ticket TTL), **M11** (gate precision), **M10** (demand model), **M12** (buffer, only if M10 says so), **M7** (cost model) |
| **Delegate** (Low importance, low effort) | Batch and assign | **L2**, **L3**, **L9**, **L13**, **L15**, **L17** |
| **Defer** (Low importance, high effort) | Revisit next iteration | **M6** (per-component TCO), **M9** (automated right-sizing), **L7**/**L8** (data-transfer modelling), **L16** (carbon data) |

### Solution Characteristics (Do First and Plan)

**M1 — Cost guardrails** · *SMART:* Add `AWS::Budgets::Budget` with a forecasted-spend alert, an estimated-charges alarm and Cost Anomaly Detection active **within one week**, verified by a test threshold that actually fires. *Owner:* demo-account owner. *Simple:* Budgets + one alarm, no pipeline. *Two-way door:* additive and removable. *Pattern:* the same three-resource guardrail applies to every future stack.

**M2 — Tags** · *SMART:* A `Globals` `Tags` block (`Environment`, `Workload`, `StackVersion`, `Owner`) on 100% of resources **within one week**, verified by `git grep -c "Tags:"` and a cost-allocation check in Cost Explorer. *Owner:* infra. *Simple:* one YAML block. *Two-way door:* additive.

**M13 — Prove the optimisation** · *SMART:* Run `eval/run_benchmark.py` against both deployed stacks on the 100-ticket dataset and publish route distribution, cost per 10k, p95 latency, GB-seconds, frontier-token reduction and **P1 recall**, with **no more than a 1 percentage-point P1 recall regression**, **within two weeks of the stacks going live**. *Owner:* backend. *Simple:* the harness already computes every field (`run_benchmark.py:306-330`). *Two-way door:* results decide whether the gate needs work; the code need not change to measure. *Pattern:* repeatable, and it is the evidence base for the published claim.

**M4 — Ticket TTL** · *SMART:* Add an `expires_at` TTL attribute to `TicketsTable` with a 30-day retention **within two weeks**, mirroring the cache-table pattern already in the template (`template.yaml:100-102`). *Owner:* backend. *Simple:* copy the existing TTL block. *Two-way door:* retention period is one number.

**M11 — Gate precision** · *SMART:* Raise gate coverage above **zero false negatives on ground-truth P1s** while keeping routine traffic on Micro, measured by route distribution on the 100-ticket dataset, **within four weeks**. *Owner:* backend. *Simple:* extend the keyword set / add severity signals rather than training a classifier. *Two-way door:* the gate is one function (`router.py:248-252`).

---

## Prioritized Remediation Plan

> **Status:** every v2 item below was **implemented at `1c3219f` and verified by the offline suite (58 passed)**. Nothing is deployed; no runtime metric has been produced. The items listed are the **remaining** gaps.

### Quick Wins (< 1 week) — "Do First"

| Finding | Action | SMART Goal | Owner | Effort |
|---------|--------|-----------|-------|--------|
| M1 | Budget + forecasted-spend alert + estimated-charges alarm | Alert fires on a test threshold within 1 week | Account owner | ~1 h |
| M2 | `Globals` `Tags` block | 100% of resources tagged within 1 week | Infra | ~30 min |
| M3 | Cost Anomaly Detection monitor | Detector live and wired to a human channel within 1 week | Account owner | ~30 min |
| L5 | v1 stack retirement date | Date recorded and tagged before the comparison ends | Infra | ~15 min |

### Foundation (1–4 weeks) — "Plan"

| Finding | Action | Phases | Effort | Dependencies |
|---------|--------|--------|--------|--------------|
| M13 | Run + publish the v1↔v2 benchmark | 1) deploy both stacks → 2) run → 3) publish route distribution, cost, p95, GB-s, P1 recall | ~1 day once live | Live deployment |
| M5 | Five-component cost baseline | 1) instrument API GW/Lambda/DynamoDB/Logs → 2) one 100-ticket run → 3) delta report | ~1 day | M13 |
| M4 | Ticket TTL | 1) TTL attribute → 2) retention decision | ~2 h | None |
| M11 | Gate precision | 1) measure per-ticket route decisions → 2) extend signals → 3) re-run benchmark | 2–3 days | M13 |
| M10 | Demand model | 1) model rate/rate-of-change → 2) confirm or revise 25/50 | 1–2 days | M13 |

### Strategic (1–3 months) — "Plan" (complex)

| Finding | Action | Phases | Effort | Dependencies |
|---------|--------|--------|--------|--------------|
| M12 | Burst absorption (SQS in front of triage, idempotent consumer) | 1) decide from M10 → 2) async contract → 3) implement + load test | 1–2 weeks | Only if M10 shows bursts that must be absorbed |
| M14/L16 | Efficiency + sustainability measurement (RUE, proxy metrics) | 1) define RUE per ticket → 2) proxy-metric export → 3) dashboard widgets | 1–2 weeks | M5 |

### Delegate (batch & assign)

| Finding | Action | Owner | Effort |
|---------|--------|-------|--------|
| L2, L3 | Per-phase cost split + cost-per-outcome in `/stats` | Backend | ~2 h |
| L9, L13 | Write the cost requirement; create the monthly review runbook with a named owner | Team lead | ~1 h |
| L15, L17 | RUE dashboard widgets; stack teardown date | Backend / Infra | ~1 h |
| L6, L7, L8 | Data-transfer note + payload-size check | Infra | ~2 h |

### Deferred — Revisit Next Iteration

| Finding | Why deferred |
|---------|--------------|
| **M6** COST05-BP03 (per-component TCO) | Needs M5's baseline first. |
| **M9** COST06-BP03 (automated right-sizing) | Depends on M8's measurement; no decision is blocked. |
| **L16** SUS01-BP02 (carbon data) | Only meaningful at real volume; proxy metrics (L15) deliver most value first. |
| **C1**, **C2** | Human decisions (process cadence; Region/sustainability alignment). |
| **NOT-A-BP residual: timeout budget** | Two-hop worst case ≈36 s vs 29 s. Recorded here rather than as a COST/SUS finding because it is a Reliability concern; fix by capping total attempts across the pair. |

---

## Next Steps

1. **Govern the spend you just learned to optimise (M1, M2, M3).** v2 cut the unit cost; it did not add a single budget, tag or alarm. This is one afternoon and it is what turns a demo into something you can leave running.
2. **Prove the claim (M13).** Deploy v1 and v2, run the unchanged harness, and publish route distribution, cost per 10k, p95, GB-seconds, frontier-token reduction **and P1 recall**. Until then, 55–85% is a design expectation, not a result.
3. **Close the retention half you left open (M4).** The cache got a TTL; `TicketsTable` did not. Mirror the pattern.
4. **Then tune the gate (M11), not the principle.** The router is the right shape; the gate firing on 1 of 100 tickets means the guardrail — not the gate — is doing the work. That is honest today, and it should be either improved or explicitly documented.
5. **Fix the two-hop timeout arithmetic before real traffic.** `router.py:34-36` plus `max_attempts=2` can exceed the 29 s Lambda timeout in the pathological case; cap total attempts across the pair.

---

*Method: pillar-scoped AWS Well-Architected review against the frozen corpus reused from the v1-before run (TOC index retrieved 2026-11-26T07:15:59Z; manifest `valid: true`; 47 in-scope BPs, ID set identical to the v1 ledger). Assessment is code/IaC-only at commit `1c3219f`; ModelShield v2 is not deployed, and no cost, latency or accuracy number in this report is a measurement. Offline suite executed: 58 passed. This report is the `after` state of a closed loop whose `before` state is `docs/war-before.md`, with per-BP traceability in `docs/war-diff.md`.*
