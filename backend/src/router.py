"""Confidence-gated adaptive model router (v2).

One cohesive fix with four stages:

0. Normalised cache lookup (fail-open).
1. Deterministic complexity gate: long or multi-signal tickets go straight to
   Nova Pro, because a cheap model should not triage an active outage.
2. Nova Micro for everything routine.
3. Confidence and P1 guardrail: anything below 0.85 confidence, or any P1
   classification, is re-run on Nova Pro.

Escalations are accounted as **Micro + Pro** so the cost telemetry does not
flatter the optimisation.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from botocore.config import Config

from bedrock_client import NOVA_MICRO, NOVA_PRO, BedrockClient, BedrockInvocationError, Invocation
from cache import ResponseCache, build_cache_key
from prompts import SYSTEM_PROMPT, build_user_prompt
from schemas import CATEGORIES, SEVERITIES, ModelResponseError, parse_model_response

LOGGER = logging.getLogger(__name__)

# Two sequential calls must fit inside the 29 s Lambda timeout. Micro is a
# short classification; Pro is allowed a little more room for the escalation.
_MICRO_CONFIG = Config(connect_timeout=2, read_timeout=6, retries={"max_attempts": 0})
_PRO_CONFIG = Config(connect_timeout=2, read_timeout=8, retries={"max_attempts": 0})
_ROUTER_MAX_ATTEMPTS = 2

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

COMPLEXITY_CHAR_THRESHOLD = 900
COMPLEXITY_TRIGGER_THRESHOLD = 2
DEFAULT_CONFIDENCE_THRESHOLD = 0.85


@dataclass(frozen=True)
class RouteOutcome:
    """Final triage plus the routing facts the handler needs for telemetry."""

    triage: Dict[str, Any]
    telemetry: Dict[str, Any]


class AdaptiveRouter:
    """Stage 0-3 routing with fail-open cache and honest escalation billing."""

    def __init__(
        self,
        pro_client: BedrockClient,
        micro_client: BedrockClient,
        cache: ResponseCache,
        confidence_threshold: Optional[float] = None,
    ) -> None:
        self._pro = pro_client
        self._micro = micro_client
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
        if cached is not None and self._valid_payload(cached):
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

        micro_invocation: Optional[Invocation] = None
        try:
            micro_invocation = self._call(self._micro, ticket)
            micro_triage = parse_model_response(micro_invocation.text)
        except (BedrockInvocationError, ModelResponseError) as exc:
            LOGGER.warning(
                "micro_path_failed ticket_id=%s error=%s",
                ticket["ticket_id"],
                type(exc).__name__,
            )
            return self._fallback(ticket, key, micro_invocation)

        if (
            micro_triage["confidence"] < self.confidence_threshold
            or micro_triage["severity"] == "P1"
        ):
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
                        input_tokens=micro_invocation.input_tokens + pro_invocation.input_tokens,
                        output_tokens=micro_invocation.output_tokens + pro_invocation.output_tokens,
                        frontier_tokens=pro_invocation.total_tokens,
                        cost_usd=micro_invocation.estimated_cost_usd
                        + pro_invocation.estimated_cost_usd,
                    ),
                ),
            )

        LOGGER.info("route=nova_micro ticket_id=%s", ticket["ticket_id"])
        return self._store(
            key,
            RouteOutcome(
                triage=micro_triage,
                telemetry=self._invocation_telemetry("nova_micro", micro_invocation),
            ),
        )

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
        micro_invocation: Optional[Invocation],
    ) -> RouteOutcome:
        pro_invocation = self._call(self._pro, ticket)
        triage = parse_model_response(pro_invocation.text)

        micro_cost = micro_invocation.estimated_cost_usd if micro_invocation else 0.0
        micro_input = micro_invocation.input_tokens if micro_invocation else 0
        micro_output = micro_invocation.output_tokens if micro_invocation else 0

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
                    input_tokens=micro_input + pro_invocation.input_tokens,
                    output_tokens=micro_output + pro_invocation.output_tokens,
                    frontier_tokens=pro_invocation.total_tokens,
                    cost_usd=micro_cost + pro_invocation.estimated_cost_usd,
                ),
            ),
        )

    def _invocation_telemetry(self, route: str, invocation: Invocation) -> Dict[str, Any]:
        is_frontier = invocation.model_id == NOVA_PRO or route in {"direct_pro"}
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
        try:
            self._cache.put(key, outcome.triage)
        except Exception as exc:  # write-through is best effort
            LOGGER.warning("cache_write_unexpected error=%s", type(exc).__name__)
        return outcome


def build_router(confidence_threshold: Optional[float] = None) -> AdaptiveRouter:
    """Production wiring: one Pro client, one Micro client, one TTL table."""

    return AdaptiveRouter(
        pro_client=BedrockClient(
            model_id=NOVA_PRO,
            client_config=_PRO_CONFIG,
            max_attempts=_ROUTER_MAX_ATTEMPTS,
        ),
        micro_client=BedrockClient(
            model_id=NOVA_MICRO,
            client_config=_MICRO_CONFIG,
            max_attempts=_ROUTER_MAX_ATTEMPTS,
        ),
        cache=ResponseCache(),
        confidence_threshold=confidence_threshold,
    )
