# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in **ModelShield**, please report it responsibly rather than opening a public issue:

- Use GitHub **Private Vulnerability Reporting** on the `ksiddhaarth07/Modelshield` repository **Security** tab.
- Include a clear reproduction summary, affected endpoint or module, and potential impact.

Do not include live AWS credentials, Cognito tokens, or customer ticket payloads in bug reports.

## Security Architecture Summary

ModelShield enforces defense-in-depth controls across API, compute, AI inference, and storage boundaries:

1. **Identity & Access Control:** `POST /triage` and `GET /stats` require verified Amazon Cognito JWTs (`iss`, `aud`/`client_id`, `exp`, `nbf`, `sub`, signature). `GET /stats` requires administrative group/scope RBAC. `GET /health` is public and exposes minimal status metadata only.
2. **Tenant Isolation:** Cache keys (`ResponseCacheTable`), persisted ticket records (`TicketsTable`), and `/stats` queries are strictly partitioned by verified JWT tenant claims (`custom:tenant_id` or isolated `user:<sub>`). Request body identity fields (`tenant_id`, `user_id`, `role`, `is_admin`) cannot override verified claims.
3. **Abuse & Cost Protection:** Per-user and per-tenant atomic DynamoDB sliding/fixed-window rate limiters, API Gateway route throttling, Lambda reserved concurrency, and strict HTTP payload byte ceilings (`413`) mitigate Bedrock cost exhaustion.
4. **AI & Prompt-Injection Guardrails:** Untrusted ticket subjects and bodies are wrapped in `<untrusted_ticket_*>` delimiters, checked deterministically for prompt-injection and active P1 security threats, validated against strict JSON output schemas, screened against prompt/credential leak patterns, and flagged with `requires_human_review` for high-impact decisions.
5. **Automated Supply-Chain CI:** `.github/workflows/security.yml` runs Gitleaks, Bandit SAST, `pip-audit`, `npm audit`, `pytest` security tests, and CodeQL alongside weekly Dependabot checks.
