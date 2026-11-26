"""Two-tier adaptive model router (v2).

Stages:

0. Normalised cache lookup (fail-open, P1 results are never cached).
1. Deterministic complexity gate: long or multi-signal tickets go straight to
   Nova Pro, because a cheap model should not triage an active outage.
2. Amazon Nova Lite for everything routine.
3. Targeted escalation: Nova Lite predictions are re-run on Nova Pro when the
   classification is P1, P3/how_to, or below the confidence floor.

The escalation rules were tuned against a per-ticket Lite-vs-Pro disagreement
diff on the 100-ticket benchmark. They are deliberately narrow: broad rules
("escalate every P2") restored accuracy but destroyed the cost saving.

Escalations are billed as **Lite + Pro** so the telemetry does not flatter the
optimisation, and frontier_tokens_used counts Pro tokens only.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from botocore.config import Config

from bedrock_client import NOVA_LITE, NOVA_PRO, BedrockClient, BedrockInvocationError, Invocation
from cache import ResponseCache, build_cache_key
from prompts import SYSTEM_PROMPT, build_user_prompt
from schemas import CATEGORIES, SEVERITIES, ModelResponseError, parse_model_response

LOGGER = logging.getLogger(__name__)

# Worst case: Lite (1 + 8) once, then Pro (1 + 8) once = 18 s, inside the 29 s
# Lambda timeout and the <20 s retry budget.
_LITE_CONFIG = Config(connect_timeout=1, read_timeout=8, retries={"max_attempts": 0})
_PRO_CONFIG = Config(connect_timeout=1, read_timeout=8, retries={"max_attempts": 0})
_LITE_MAX_ATTEMPTS = 1
_PRO_MAX_ATTEMPTS = 1

HIGH_RISK_KEYWORDS: Sequence[str] = (
    "outage",
    "production down",
    "data loss",
    "breach",
    "unauthorized",
    "privilege escalation",
    "corruption",
    "503",
    "failover",
    "security incident",
)

# Clear active P1 crisis phrases: one match sends straight to Nova Pro (1 hop)
# rather than paying a wasted Nova Lite call and doubling tail latency.
CRITICAL_P1_SIGNALS: Sequence[str] = (
    "privilege escalation",
    "public repository",
    "public github",
    "shard corruption",
    "down for all tenants",
    "all regions",
    "unauthorized admin",
    "exposing customer",
    "publicly reachable",
    "double-charging",
    "returning 500",
    "error rate is 100%",
    "ransomware",
    "multi-region database replication lag",
    "failing writes",
)

COMPLEXITY_CHAR_THRESHOLD = 900
COMPLEXITY_TRIGGER_THRESHOLD = 2
DEFAULT_CONFIDENCE_THRESHOLD = 0.85


@dataclass(frozen=True)
class RouteOutcome:
    """Final triage plus the routing facts the handler needs for telemetry."""

    triage: Dict[str, Any]
    telemetry: Dict[str, Any]


class AdaptiveRouter:
    """Cache -> complexity gate -> Nova Lite -> targeted Nova Pro escalation."""

    def __init__(
        self,
        pro_client: BedrockClient,
        lite_client: BedrockClient,
        cache: ResponseCache,
        confidence_threshold: Optional[float] = None,
    ) -> None:
        self._pro = pro_client
        self._lite = lite_client
        self._cache = cache

        if confidence_threshold is None:
            raw = os.environ.get("CONFIDENCE_THRESHOLD", str(DEFAULT_CONFIDENCE_THRESHOLD))
            try:
                confidence_threshold = float(raw)
            except ValueError:
                confidence_threshold = DEFAULT_CONFIDENCE_THRESHOLD
        self.confidence_threshold = confidence_threshold

    def route(self, ticket: Dict[str, str]) -> RouteOutcome:
        key = build_cache_key(ticket["subject"], ticket["body"])

        cached = self._safe_cache_get(key)
        if cached is not None and self._valid_payload(cached) and cached.get("severity") != "P1":
            LOGGER.info("cache_hit ticket_id=%s", ticket["ticket_id"])
            return RouteOutcome(
                triage=cached,
                telemetry=self._telemetry(
                    route="cache_hit",
                    model_id="cache",
                    cache_hit=True,
                    escalated=False,
                    fallback=False,
                    input_tokens=0,
                    output_tokens=0,
                    frontier_tokens=0,
                    cost_usd=0.0,
                ),
            )

        if self._is_complex(ticket):
            invocation = self._call(self._pro, ticket)
            triage = parse_model_response(invocation.text)
            LOGGER.info("route=direct_pro ticket_id=%s", ticket["ticket_id"])
            return self._store(
                key,
                RouteOutcome(
                    triage=triage,
                    telemetry=self._invocation_telemetry("direct_pro", invocation),
                ),
            )

        lite_invocation: Optional[Invocation] = None
        try:
            lite_invocation = self._call(self._lite, ticket)
            lite_triage = parse_model_response(lite_invocation.text)
        except (BedrockInvocationError, ModelResponseError) as exc:
            LOGGER.warning(
                "lite_path_failed ticket_id=%s error=%s detail=%s",
                ticket["ticket_id"],
                type(exc).__name__,
                str(exc)[:120],
            )
            return self._fallback(ticket, key, lite_invocation)

        if self._needs_pro(lite_triage):
            pro_invocation = self._call(self._pro, ticket)
            pro_triage = parse_model_response(pro_invocation.text)
            LOGGER.info("route=escalated_pro ticket_id=%s", ticket["ticket_id"])
            return self._store(
                key,
                RouteOutcome(
                    triage=pro_triage,
                    telemetry=self._telemetry(
                        route="escalated_pro",
                        model_id=pro_invocation.model_id,
                        cache_hit=False,
                        escalated=True,
                        fallback=False,
                        input_tokens=lite_invocation.input_tokens + pro_invocation.input_tokens,
                        output_tokens=lite_invocation.output_tokens + pro_invocation.output_tokens,
                        frontier_tokens=pro_invocation.total_tokens,
                        cost_usd=lite_invocation.estimated_cost_usd
                        + pro_invocation.estimated_cost_usd,
                    ),
                ),
            )

        LOGGER.info("route=nova_lite ticket_id=%s", ticket["ticket_id"])
        return self._store(
            key,
            RouteOutcome(
                triage=lite_triage,
                telemetry=self._invocation_telemetry("nova_lite", lite_invocation),
            ),
        )

    def _needs_pro(self, triage: Dict[str, Any]) -> bool:
        severity = triage["severity"]
        category = triage["category"]
        if severity == "P1":
            return True
        if severity == "P3" and category == "how_to":
            return True
        return triage["confidence"] < self.confidence_threshold

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _call(client: BedrockClient, ticket: Dict[str, str]) -> Invocation:
        return client.converse(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_user_prompt(ticket),
        )

    def _fallback(
        self,
        ticket: Dict[str, str],
        key: str,
        lite_invocation: Optional[Invocation],
    ) -> RouteOutcome:
        pro_invocation = self._call(self._pro, ticket)
        triage = parse_model_response(pro_invocation.text)

        lite_cost = lite_invocation.estimated_cost_usd if lite_invocation else 0.0
        lite_input = lite_invocation.input_tokens if lite_invocation else 0
        lite_output = lite_invocation.output_tokens if lite_invocation else 0

        LOGGER.info("route=fallback_pro ticket_id=%s", ticket["ticket_id"])
        return self._store(
            key,
            RouteOutcome(
                triage=triage,
                telemetry=self._telemetry(
                    route="fallback_pro",
                    model_id=pro_invocation.model_id,
                    cache_hit=False,
                    escalated=False,
                    fallback=True,
                    input_tokens=lite_input + pro_invocation.input_tokens,
                    output_tokens=lite_output + pro_invocation.output_tokens,
                    frontier_tokens=pro_invocation.total_tokens,
                    cost_usd=lite_cost + pro_invocation.estimated_cost_usd,
                ),
            ),
        )

    def _invocation_telemetry(self, route: str, invocation: Invocation) -> Dict[str, Any]:
        heavy_id = getattr(self._pro, "model_id", NOVA_PRO)
        is_frontier = invocation.model_id == heavy_id or route == "direct_pro"
        return self._telemetry(
            route=route,
            model_id=invocation.model_id,
            cache_hit=False,
            escalated=False,
            fallback=False,
            input_tokens=invocation.input_tokens,
            output_tokens=invocation.output_tokens,
            frontier_tokens=invocation.total_tokens if is_frontier else 0,
            cost_usd=invocation.estimated_cost_usd,
        )

    @staticmethod
    def _telemetry(
        *,
        route: str,
        model_id: str,
        cache_hit: bool,
        escalated: bool,
        fallback: bool,
        input_tokens: int,
        output_tokens: int,
        frontier_tokens: int,
        cost_usd: float,
    ) -> Dict[str, Any]:
        return {
            "route_decision": route,
            "model_id": model_id,
            "cache_hit": cache_hit,
            "escalated": escalated,
            "fallback_triggered": fallback,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "frontier_tokens_used": int(frontier_tokens),
            "estimated_cost_usd": round(float(cost_usd), 10),
        }

    @staticmethod
    def _is_complex(ticket: Dict[str, str]) -> bool:
        text = f"{ticket['subject']}\n{ticket['body']}".lower()
        if any(signal in text for signal in CRITICAL_P1_SIGNALS):
            return True
        triggers = sum(1 for keyword in HIGH_RISK_KEYWORDS if keyword in text)
        length = len(ticket["subject"]) + len(ticket["body"])
        return length > COMPLEXITY_CHAR_THRESHOLD or triggers >= COMPLEXITY_TRIGGER_THRESHOLD

    @staticmethod
    def _valid_payload(payload: Dict[str, Any]) -> bool:
        return (
            isinstance(payload, dict)
            and payload.get("severity") in SEVERITIES
            and payload.get("category") in CATEGORIES
            and isinstance(payload.get("summary"), str)
            and isinstance(payload.get("draft_reply"), str)
        )

    def _safe_cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            return self._cache.get(key)
        except Exception as exc:  # never let the cache break triage
            LOGGER.warning("cache_read_unexpected error=%s", type(exc).__name__)
            return None

    def _store(self, key: str, outcome: RouteOutcome) -> RouteOutcome:
        # A live P1 must never be replayed from a 24 h cache.
        if outcome.triage.get("severity") == "P1":
            LOGGER.info("cache_skip_p1")
            return outcome
        try:
            self._cache.put(key, outcome.triage)
        except Exception as exc:  # write-through is best effort
            LOGGER.warning("cache_write_unexpected error=%s", type(exc).__name__)
        return outcome


def build_router(confidence_threshold: Optional[float] = None) -> AdaptiveRouter:
    """Production wiring: one Pro client, one Lite client, one TTL table."""

    heavy_model = os.environ.get("HEAVY_MODEL_ID") or os.environ.get("MODEL_ID") or NOVA_PRO
    light_model = os.environ.get("LIGHT_MODEL_ID") or NOVA_LITE
    return AdaptiveRouter(
        pro_client=BedrockClient(
            model_id=heavy_model,
            client_config=_PRO_CONFIG,
            max_attempts=_PRO_MAX_ATTEMPTS,
        ),
        lite_client=BedrockClient(
            model_id=light_model,
            client_config=_LITE_CONFIG,
            max_attempts=_LITE_MAX_ATTEMPTS,
        ),
        cache=ResponseCache(),
        confidence_threshold=confidence_threshold,
    )
