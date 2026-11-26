# ModelShield — Final Release Verification Evidence

**Region:** `ap-southeast-2` · **Dataset:** `eval/dataset_100_tickets.json` (`100` tickets, `11` ground-truth P1s, `5` repeat groups = `15` expected cache hits) · **Concurrency / Pacing:** `2` / `2.5 s`

---

## 1. Two Independent Live Benchmark Runs

Cache (`modelshield-v2-response-cache`) was cleared before **both** runs (`Cleared 0 cache items` before Run 1; `Cleared 74 cache items` before Run 2).

| Metric | Run 1 `v1` | Run 1 `v2` | Run 2 `v1` | Run 2 `v2` |
|---|---|---|---|---|
| **Accuracy** | `0.94` | `0.92` (`-2.00 pp`) | `0.93` | **`0.95` (`+2.00 pp`)** |
| **P1 Recall / Precision** | `1.00` / `1.00` | **`1.00` / `1.00`** | `1.00` / `1.00` | **`1.00` / `1.00`** |
| **Cost / 10K Tickets (USD)** | `$18.6717` | **`$3.3000` (`-82.33%`)** | `$18.6454` | **`$3.2945` (`-82.33%`)** |
| **p95 Latency (ms)** | `929` | **`815` (`-12.28%`)** | `867` | **`780` (`-10.07%`)** |
| **Frontier Tokens** | `209,426` | **`25,202` (`-87.97%`)** | `209,344` | **`25,181` (`-87.97%`)** |
| **Lambda GB-Seconds** | `36.7620` | **`13.6749` (`-62.80%`)** | `36.3350` | **`13.8871` (`-61.78%`)** |
| **Cache Hits** | `0` | **`15`** | `0` | **`15`** |
| **Escalations / Fallbacks / Errors** | `0 / 0 / 0` | **`1 / 0 / 0`** | `0 / 0 / 0` | **`1 / 0 / 0`** |
| **Disagreements (`v1 != v2`)** | `11` | | `7` | |

---

## 2. Per-Ticket Disagreement Analysis

### Run 1 — All 11 Disagreements (`eval/results/benchmark_report.json`)

- **4 where `v2` beat `v1`:** `tkt-060`, `tkt-061`, `tkt-063` (`P3/incident` — `v2` correct on Nova Lite + 2 cache hits; `v1` over-classified `P2/incident`) and `tkt-091` (`P2/security` — `v2` correct; `v1` predicted `P2/incident`).
- **1 where both missed:** `tkt-046` (`gt=P3/bug`, `v1=P2/incident`, `v2=P3/incident`).
- **6 where `v1` beat `v2`:** `tkt-033` (`P3/billing` → `v2=P4/how_to`), `tkt-100` (`P2/bug` → `v2=P3/bug`), plus repeat group `tkt-064..067` (`gt=P2/account` — `v2` Nova Lite predicted `P2/incident` on `064` and replayed via cache on `065..067`).

| Ticket | Ground Truth | `v1` (`ok`) | `v2` (`ok`, `conf`, `route`, `latency`) |
|---|---|---|---|
| `tkt-033` | `P3/billing` | `P3/billing` (`True`) | `P4/how_to` (`False`, `0.95`, `nova_lite`, `538 ms`) |
| `tkt-046` | `P3/bug` | `P2/incident` (`False`) | `P3/incident` (`False`, `0.90`, `nova_lite`, `581 ms`) |
| `tkt-060` | `P3/incident` | `P2/incident` (`False`) | `P3/incident` (`True`, `0.90`, `nova_lite`, `640 ms`) |
| `tkt-061` | `P3/incident` | `P2/incident` (`False`) | `P3/incident` (`True`, `0.90`, `cache_hit`, `3 ms`) |
| `tkt-063` | `P3/incident` | `P2/incident` (`False`) | `P3/incident` (`True`, `0.90`, `cache_hit`, `4 ms`) |
| `tkt-064` | `P2/account` | `P2/account` (`True`) | `P2/incident` (`False`, `0.92`, `nova_lite`, `676 ms`) |
| `tkt-065` | `P2/account` | `P2/account` (`True`) | `P2/incident` (`False`, `0.92`, `cache_hit`, `3 ms`) |
| `tkt-066` | `P2/account` | `P2/account` (`True`) | `P2/incident` (`False`, `0.92`, `cache_hit`, `13 ms`) |
| `tkt-067` | `P2/account` | `P2/account` (`True`) | `P2/incident` (`False`, `0.92`, `cache_hit`, `17 ms`) |
| `tkt-091` | `P2/security` | `P2/incident` (`False`) | `P2/security` (`True`, `0.88`, `nova_lite`, `578 ms`) |
| `tkt-100` | `P2/bug` | `P2/bug` (`True`) | `P3/bug` (`False`, `0.90`, `nova_lite`, `637 ms`) |

### Run 2 — All 7 Disagreements (`eval/results/benchmark_report_run2.json`)

- **4 where `v2` beat `v1`:** `tkt-060..063` (`P3/incident` — `v2` correct via Lite + 3 cache hits; `v1` predicted `P2/incident`).
- **1 where both missed:** `tkt-046` (`gt=P3/bug`, `v1=P2/incident`, `v2=P3/incident`).
- **2 where `v1` beat `v2`:** `tkt-033` (`P3/billing` → `v2=P4/how_to`), `tkt-100` (`P2/bug` → `v2=P3/bug`).

### P1 Severity & Category Check (Runs 1 & 2)

- **0 P1 severity errors** in both `v1` (`11/11`) and `v2` (`11/11`) across both runs (`100%` recall, `100%` precision).
- **0 P1 category errors** in both `v1` and `v2` (`11/11` exact `(severity, category)` matches).

---

## 3. Confusion Matrices

### Run 1 (`v1` vs `v2`, rows = ground truth, cols = predicted)

**Severity (`v1` / `v2`):**
- `v1`: `P1` 11/11 · `P2` 27/27 · `P3` 36/41 (`4`→`P2`, `1`→`P4`) · `P4` 21/21
- `v2`: `P1` 11/11 · `P2` 26/27 (`1`→`P3`) · `P3` 39/41 (`2`→`P4`) · `P4` 21/21

**Category (`v1` / `v2`):**
- `v1`: `account` 18/18 · `billing` 17/18 (`1`→`how_to`) · `bug` 4/5 (`1`→`incident`) · `how_to` 21/21 · `incident` 30/30 · `security` 7/8 (`1`→`incident`)
- `v2`: `account` 14/18 (`4`→`incident` via `tkt-064..067`) · `billing` 16/18 (`2`→`how_to`) · `bug` 4/5 (`1`→`incident`) · `how_to` 21/21 · `incident` 30/30 · `security` 8/8

### Run 2 (`v1` vs `v2`)

**Severity (`v1` / `v2`):**
- `v1`: `P1` 11/11 · `P2` 27/27 · `P3` 35/41 (`5`→`P2`, `1`→`P4`) · `P4` 21/21
- `v2`: `P1` 11/11 · `P2` 26/27 (`1`→`P3`) · `P3` 39/41 (`2`→`P4`) · `P4` 21/21

**Category (`v1` / `v2`):**
- `v1`: `account` 18/18 · `billing` 17/18 (`1`→`how_to`) · `bug` 4/5 (`1`→`incident`) · `how_to` 21/21 · `incident` 30/30 · `security` 7/8 (`1`→`incident`)
- `v2`: `account` 18/18 · `billing` 16/18 (`2`→`how_to`) · `bug` 4/5 (`1`→`incident`) · `how_to` 21/21 · `incident` 30/30 · `security` 8/8

---

## 4. Deployed AWS Lambda Architecture & Model ID Verification

Source: `eval/results/lambda_architecture_diff.json` (captured via `aws lambda get-function-configuration`).

| Property | `modelshield-v1-TriageFunction-HXHu2RjpB4N1` | `modelshield-v2-TriageFunction-igjt5hFeFuPL` |
|---|---|---|
| `Architectures` | **`["x86_64"]`** | **`["arm64"]`** |
| `MemorySize` | `512` MB | `256` MB |
| `Runtime` / `Timeout` | `python3.13` / `29 s` | `python3.13` / `29 s` |
| `HEAVY_MODEL_ID` | `apac.amazon.nova-pro-v1:0` | `apac.amazon.nova-pro-v1:0` |
| `LIGHT_MODEL_ID` | `apac.amazon.nova-lite-v1:0` | `apac.amazon.nova-lite-v1:0` |
| `RESPONSE_CACHE_TABLE` | `""` | `modelshield-v2-response-cache` |
| `TICKETS_TABLE` | `modelshield-v1-tickets` | `modelshield-v2-tickets` |
| Actual inference `model_id`s (Run 1) | `nova-pro`: `100` | `nova-lite`: `73`, `cache`: `15`, `nova-pro`: `12` (`11` direct + `1` escalated) |

Model IDs match 100% across `README.md`, `infra/samconfig.toml`, `infra/template.yaml`, `GET /health`, Lambda environment variables, and live inference telemetry.

---

## 5. Saved Evidence Artifacts (`eval/results/`)

- `eval/results/benchmark_report.json` (Run 1 live report)
- `eval/results/benchmark_report_run2.json` (Run 2 independent live report)
- `eval/results/cloudwatch_metrics_v1.json` (7 `ModelShield/Triage` metrics for `v1`)
- `eval/results/cloudwatch_metrics_v2.json` (7 `ModelShield/Triage` metrics for `v2`)
- `eval/results/lambda_architecture_diff.json` (deployed `v1` vs `v2` Lambda configs & architectures)
- `eval/results/verification_evidence.md` (this summary)
