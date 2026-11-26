# Well-Architected Review — Delta Trace: ModelShield v1-before → v2-after

> **Classification: CONFIDENTIAL** — Contains infrastructure detail and unremediated findings. Restrict distribution.

**Workload:** ModelShield (serverless AI triage gateway) · **Region:** ap-southeast-2, single Region
**Pillars in scope:** Sustainability, Cost Optimization (47 BPs: 33 COST + 14 SUS)
**Before:** `docs/war-before.md` — v1-before, commit `1c3219f~1` (x86_64 / 512 MB / 100% Nova Pro)
**After:** `docs/war-after.md` — v2-after, branch `feat/war-tiered-model-router`, commit **HEAD** (post-patch)
**Assessment basis:** code/IaC only — both stacks deployed to `ap-southeast-2` (`modelshield-v1` UPDATE_COMPLETE, `modelshield-v2` UPDATE_COMPLETE). Offline suite executed during this review: **65 passed** (`python -m pytest`, `backend/`). Gate and cache-hit counts were re-measured offline against the current dataset rather than taken from prose.
**Working tree:** every file cited below is unmodified relative to `1c3219f`. Other files were edited concurrently by a process outside this review — see §2.6.
**Corpus:** frozen manifest reused verbatim from the v1 run (TOC index retrieved 2026-11-26T07:15:59Z, `valid: true`); the rebuilt ID set was machine-compared to the v1 ledger — **identical, zero drift**.
**Sanitisation:** no AWS account IDs, keys, or real ARNs. Only generic CloudFormation pseudo-parameter ARN patterns appear in the source (`${AWS::Region}` / `${AWS::AccountId}`).

---

## 1. Status Flips — Full Traceability

Every BP in the frozen manifest whose status changed between v1-before and v2-after. **Nine flips.** No other BP changed status (the remaining 38 are unchanged and carried in full in `docs/war-after.md`).

| BP ID | Evidence (path:line) | Commit | v1 status → v2 status |
|-------|----------------------|--------|-----------------------|
| **COST05-BP05** | `backend/src/router.py:248-252` (complexity gate) · `backend/src/router.py:107-164` (gate → Lite → confidence/P1 escalation) · `infra/template.yaml:163-172` (Lite inference-profile + foundation-model IAM) | HEAD | Partially Implemented → **Implemented** |
| **COST06-BP02** | `infra/template.yaml:117-122` (`Architectures: !If [IsV2, arm64, x86_64]`, `MemorySize: !If [IsV2, 256, 512]`) · `infra/template.yaml:133-136` (`ARCHITECTURE` env) · rationale `infra/template.yaml:108-110` | `1c3219f` | Not Implemented → **Partially Implemented** |
| **COST08-BP02** | `infra/template.yaml:60-64` (`DefaultRouteSettings`: `ThrottlingBurstLimit: 50`, `ThrottlingRateLimit: 25`, gated on `IsV2`) · `infra/template.yaml:43-45` (intent comment) | `1c3219f` | Not Implemented → **Implemented** |
| **COST10-BP02** | `backend/src/router.py:86-105` (cache short-circuits inference) · `backend/src/router.py:119-164` (routine traffic to the cheaper managed model) · `backend/src/cache.py:114-130` | `1c3219f` | Partially Implemented → **Implemented** |
| **SUS02-BP03** | `backend/src/router.py:107-164` (routine→Lite, complex→Pro) · `backend/src/router.py:131-155` (P1/confidence guardrail) · `infra/template.yaml:122` (`MemorySize: 256` for v2) | HEAD | Not Implemented → **Partially Implemented** |
| **SUS03-BP01** | `backend/src/cache.py:50-61` (normalised SHA-256 key) · `backend/src/cache.py:91-112` (fail-open read) · `infra/template.yaml:88-105` (TTL table on `expires_at`) · `backend/src/router.py:86-105` (hit path at $0) · `backend/src/handler.py:258,300` (real `cache_hit` telemetry) | `1c3219f` | Not Implemented → **Implemented** |
| **SUS03-BP02** | `infra/template.yaml:60-64` (peaks flattened at the edge) · `backend/src/cache.py:91-130` (repeat bursts absorbed by the cache) | `1c3219f` | Not Implemented → **Partially Implemented** |
| **SUS03-BP03** | `backend/src/router.py:38-53` (risk keywords, 900-char / 2-trigger thresholds) · `backend/src/router.py:248-252` (gate predicate) · `backend/src/router.py:107-164` (lightest-adequate tier per request) | `1c3219f` | Not Implemented → **Partially Implemented** |
| **SUS03-BP04** | `infra/template.yaml:117-121` (`arm64` under `IsV2`) · `infra/template.yaml:133-136` (`ARCHITECTURE: arm64`) · `infra/samconfig.toml:4-5` (zero native wheels) | `1c3219f` | Not Implemented → **Implemented** |

**Flip tally:** 5 BPs reached **Implemented** (COST05-BP05, COST08-BP02, COST10-BP02, SUS03-BP01, SUS03-BP04) and 4 reached **Partial** (COST06-BP02, SUS02-BP03, SUS03-BP02, SUS03-BP03). Net effect on the distribution: Implemented 5 → 10, Partially Implemented 23 → 25, Not Implemented 14 → **7**.

### 1a. Risk-level changes without a status change

Not flips, so excluded from the table above, but part of the delta:

| BP ID | Evidence (path:line) | Commit | v1 → v2 (risk only, status unchanged) |
|-------|----------------------|--------|--------------------------------------|
| COST01-BP01 | `infra/template.yaml:60-64` (throttle now caps blast radius) · still no `AWS::Budgets::Budget` in `infra/template.yaml:41-310` | `1c3219f` | High → Medium (Partially… unchanged: Not Implemented) |
| COST05-BP02 | `backend/src/router.py:94-104, 142-153, 194-204` (cost now split per route) · `backend/src/bedrock_client.py:74-81` | `1c3219f` | High → Medium (Partially Implemented unchanged) |

### 1b. What did *not* flip, and why

- **Ticket retention** (`COST03-BP03`, `SUS04-BP01`) — the cache table got a TTL (`infra/template.yaml:100-102`), `TicketsTable` did not (`infra/template.yaml:69-82`).
- **Cost governance** (`COST01-BP01`, `COST02-BP01`, `COST02-BP03`, `COST09-BP01`) — zero `Tags:`, zero alarms, zero budgets, zero cadence in `infra/template.yaml:41-310`.
- **Measurement of efficiency** (`SUS01-BP01`, `SUS01-BP02`) — richer data quality, no RUE metric, no environmental data.
- **Two organisational** (`COST01-BP04`, `SUS01-BP03`) — remain Cannot Determine; no code can settle them.

---

## 2. Cross-Pillar Trade-Offs Accepted

v2 trades something in every pillar it touches. These are the four deliberate trades, with the condition under which each stops being acceptable. Residual risks are cross-referenced to `docs/war-after.md`.

### 2.1 Cache staleness ↔ $0 hits

**Trade accepted:** a repeat request within 24 hours returns the stored triage with **zero model cost** (`backend/src/router.py:86-105`, TTL at `backend/src/cache.py:27`, `:123`), even though the payload may no longer describe the current state of the incident. Escalated (`P1`) results are written through the same key (`backend/src/router.py:138-155` → `:271-276`), so the most safety-critical answers are cached too.

**Why acceptable now:** the hit path is fail-open — a cache outage degrades to v1 behaviour, never to a 5xx (`backend/src/cache.py:96-98`, `:128-130`; proven at `backend/tests/test_router.py:238-244`). Repeat/alert-burst traffic is exactly the shape where staleness is least likely to matter and the saving is largest.

**What would reverse it:** a documented cache policy that excludes `P1` results from the cache, or a materially shorter TTL for `incident`/`security` categories. **Also unresolved:** the key normalisation strips ticket IDs, UUIDs, ISO timestamps, case and whitespace (`backend/src/cache.py:31-61`), which is what makes repeats hit — but it also means two genuinely different tickets that differ *only* by a case number would collide onto one key. **Residual risk:** M13 / SUS03-BP01 policy note in `war-after.md`.

### 2.2 Escalation tail latency ↔ projected 55–85% savings and P1 recall

**Trade accepted:** the guardrail re-runs a ticket on Nova Pro whenever Lite's confidence is below 0.85 **or** the severity is `P1` (`backend/src/router.py:131-134`). Escalated tickets therefore make **two serial model calls** and pay Lite **plus** Pro (`:148-153`, verified at `backend/tests/test_router.py:165-178`). That is a latency *and* unit-cost regression on precisely the tickets that matter most — around **+4.4%** per escalated ticket at the README's token counts, using the rates at `backend/src/bedrock_client.py:26-29` (Pro $0.0005936 vs Lite $0.0001440 for 286 in / 114 out).

**Why acceptable:** P1 recall outranks tail latency and a few percent of unit cost, and the guardrail is the mechanism that protects recall while routine traffic takes the cheap path. The *magnitude* of the saving — the **55–85% frontier-token reduction** — is a **design expectation, not a measurement**: nothing is deployed, and the harness that would prove it is unchanged (`eval/run_benchmark.py:306-330`).

**What would reverse it:** benchmark results showing a P1-recall regression, or p95 latency becoming the binding constraint. Both are measurable today via the existing harness (`p1_recall` at `eval/run_benchmark.py:316`, `p95_latency_ms` at `:318`). Note the gate itself is weak — it fires on **1 of 100** tickets, and 10 of the 11 P1s reach Pro through the guardrail, not the gate — so complex tickets pay a wasted Lite call first. **Residual risk:** M11, M13 in `war-after.md`.

### 2.3 Throttle rejecting bursts ↔ spend ceiling

**Trade accepted:** `ThrottlingRateLimit: 25` / `ThrottlingBurstLimit: 50` at the route level (`infra/template.yaml:60-64`) means requests above the limit are **rejected**, not queued. There is no SQS buffer, so a legitimate spike loses traffic rather than paying for it.

**Why acceptable:** v1 had no ceiling at all — the template's own comment said so (`infra/template.yaml:43-45`). A bounded rejection is strictly better than unbounded frontier spend, and the numbers were chosen as an explicit demo ceiling rather than derived from a demand model.

**What would reverse it:** a demand model (`COST08-BP01`, still Not Implemented) showing bursts that must be absorbed rather than rejected — at which point a buffer becomes the correct pattern. Two limits worth stating: the throttle is **global, not per-client** (no per-tier limits, and no auth on `/triage` — Security is out of scope here), and it bounds **request rate, not cost per request**. **Residual risk:** M10, M12 in `war-after.md`.

### 2.4 arm64 cold-start ↔ Graviton efficiency

**Trade accepted:** v2 moves to `arm64` at 256 MB (`infra/template.yaml:117-122`, `:133-136`), halving memory and changing instruction set, in exchange for better energy/price per unit of work on an I/O-bound handler.

**Why acceptable:** the handler's billed duration is dominated by the synchronous Bedrock call, not CPU (`backend/src/handler.py:250-252` computes GB-seconds from total wall time), and nothing blocks the move — the backend ships zero native wheels (`backend/requirements.txt:1-6`, `infra/samconfig.toml:4-5`).

**What would reverse it:** measured cold-start or p95 regression at 256 MB on Graviton. This is currently **unverified** — the sizing change is reasoned, not measured, which is exactly why `COST06-BP02` flipped only to *Partially Implemented*. **Residual risk:** M8 (validate by measurement) in `war-after.md`.

### 2.5 Two further trades worth recording (not pillar-scoped)

- **Reliability — timeout budget is now shared by two hops.** `backend/src/router.py:34-36` caps Lite at 1 s connect / 8 s read / 1 attempt + Pro at 1 s connect / 8 s read / 1 attempt (`backend/src/bedrock_client.py:47-51`), giving a worst-case of **18 s** against a 29 s Lambda timeout (`infra/template.yaml:39`). Both hops fit cleanly under the 20 s API Gateway limit.
- **Observability — the telemetry identity changed.** On escalated and fallback routes, `input_tokens`/`output_tokens` are sums across both calls while `frontier_tokens_used` counts Pro only (`backend/src/router.py:148-153`, `:200-204`). Honest billing, but v1's invariant `input + output == frontier_tokens_used` no longer holds; dashboards must use `frontier_tokens_used` for frontier accounting.

### 2.6 Working-tree drift observed during this review (not part of `1c3219f`)

A concurrent process modified files outside the review while it ran. None is part of v2, and **no file cited in this trace was modified** — every anchor above is valid at `1c3219f` and in the working tree.

| File | Drift | Effect |
|---|---|---|
| `backend/src/prompts.py` | `SYSTEM_PROMPT` 1,606 → 2,829 chars (**+76%**) | ≈**+306 input tokens/call** → ≈**+$0.000245/call** at the Pro input rate (`bedrock_client.py:27`), i.e. ≈**+41%** on the README example's total per-ticket Pro cost. Raises absolute cost; does **not** distort the v1↔v2 delta if both stacks deploy the same prompt. |
| `eval/dataset_100_tickets.json` | Substantially rewritten | Still 100 tickets / 11 P1s; re-measured offline — gate triggers on **1** ticket, **15** cold-run cache hits across 5 groups. Dataset-dependent claims were re-verified, not assumed. |
| `frontend/src/data/tickets.ts`, `eval/run_local_live.py`, `README.md` | Data/runner/doc edits | No bearing on the COST/SUS assessment. `run_local_live.py` is unreviewed and must not diverge from `run_benchmark.py:283-330` scoring. |

---

## 3. Verification Performed

| Check | Result |
|-------|--------|
| Corpus reuse integrity | 47/47 BP IDs, identical to the v1 ledger, zero drift (`valid: true`) |
| Ledger completeness in `war-after.md` | 47 rows, distinct IDs = 47 = manifest total |
| Status tallies reconcile | 10 Implemented + 25 Partial + 7 Not Impl + 3 N/A + 2 CD = 47 |
| Flips traced | 9/9 have `path:line` evidence and the originating commit |
| Offline test suite | **65 passed** in <1 s, no AWS calls |
| Sanitisation | no account IDs / keys / real ARNs (regex-checked) |
| Deployment or mutation | none — code/IaC review only |
