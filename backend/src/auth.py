"""Cognito JWT authentication and role-based authorization (pure stdlib).

Supports both API Gateway HTTP API JWT Authorizer context validation and
direct Bearer JWT verification (RS256 via Cognito JWKS PKCS#1 v1.5 SHA-256 and
HS256 via explicit secret for local testing) without native-wheel dependencies,
preserving Docker-free ``arm64`` SAM builds.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

# ASN.1 DigestInfo prefix for SHA-256 in RSASSA-PKCS1-v1_5 signatures (RFC 8017)
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")

_IDENTITY_SPOOF_FIELDS = frozenset(
    {
        "tenant_id",
        "user_id",
        "sub",
        "role",
        "roles",
        "groups",
        "cognito:groups",
        "is_admin",
        "permissions",
        "owner_id",
    }
)

_ADMIN_ROLES = frozenset({"admin", "modelshield-admin", "super_admin", "role:admin"})
_ADMIN_SCOPES = frozenset({"modelshield/admin", "stats:read"})
_TRIAGE_SCOPES = frozenset(
    {
        "modelshield/triage",
        "triage:write",
        "triage",
        "modelshield/admin",
        "aws.cognito.signin.user.admin",
        "openid",
    }
)

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.:@-]")

_JWKS_CACHE_LOCK = threading.Lock()
_JWKS_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_JWKS_TTL_SECONDS = 300.0


class AuthenticationError(Exception):
    """Raised when credentials are missing, malformed, expired, or untrusted."""

    status_code = 401
    error_code = "unauthorized"


class AuthorizationError(Exception):
    """Raised when an authenticated principal lacks permissions or attempts spoofing."""

    status_code = 403
    error_code = "forbidden"


@dataclass(frozen=True)
class AuthContext:
    """Verified caller identity extracted strictly from trusted JWT claims."""

    sub: str
    tenant_id: str
    roles: FrozenSet[str]
    scopes: FrozenSet[str]
    token_use: str
    issuer: str
    client_id: str


def _b64url_decode(segment: str) -> bytes:
    if not isinstance(segment, str) or not segment:
        raise AuthenticationError("Malformed JWT segment.")
    padded = segment + "=" * ((4 - len(segment) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, binascii.Error, UnicodeEncodeError) as exc:
        raise AuthenticationError("Malformed JWT encoding.") from exc


def _b64url_to_int(segment: str) -> int:
    raw = _b64url_decode(segment)
    if not raw:
        raise AuthenticationError("Invalid JWK integer.")
    return int.from_bytes(raw, "big")


def _sanitize_identifier(value: str, fallback: str = "unknown") -> str:
    cleaned = _SAFE_ID_RE.sub("_", value.strip())[:64]
    return cleaned or fallback


def _get_header(headers: Optional[Mapping[str, Any]], target: str) -> str:
    if not isinstance(headers, Mapping):
        return ""
    target_lower = target.lower()
    for key, val in headers.items():
        if isinstance(key, str) and key.lower() == target_lower and isinstance(val, str):
            return val.strip()
    return ""


def extract_bearer_token(headers: Optional[Mapping[str, Any]]) -> Optional[str]:
    auth_header = _get_header(headers, "authorization")
    if not auth_header:
        return None
    parts = auth_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthenticationError("Authorization header must use Bearer scheme.")
    return parts[1].strip()


def _parse_jwt_parts(token: str) -> Tuple[Dict[str, Any], Dict[str, Any], bytes, bytes]:
    parts = token.split(".")
    if len(parts) != 3 or any(not p for p in parts):
        raise AuthenticationError("Invalid JWT format.")
    header_raw, payload_raw, sig_raw = parts
    try:
        header = json.loads(_b64url_decode(header_raw).decode("utf-8"))
        claims = json.loads(_b64url_decode(payload_raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthenticationError("Invalid JWT JSON.") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise AuthenticationError("JWT header and claims must be JSON objects.")
    signing_input = f"{header_raw}.{payload_raw}".encode("ascii")
    signature = _b64url_decode(sig_raw)
    if not signature:
        raise AuthenticationError("JWT signature is missing.")
    return header, claims, signing_input, signature


def _verify_rs256_signature(
    signing_input: bytes, signature: bytes, jwk: Mapping[str, Any]
) -> bool:
    if jwk.get("kty") != "RSA":
        return False
    n_val = _b64url_to_int(str(jwk.get("n", "")))
    e_val = _b64url_to_int(str(jwk.get("e", "")))
    if n_val <= 0 or e_val < 3:
        return False
    key_len = (n_val.bit_length() + 7) // 8
    if len(signature) != key_len or key_len < len(_SHA256_DIGEST_INFO_PREFIX) + 32 + 11:
        return False
    sig_int = int.from_bytes(signature, "big")
    if sig_int >= n_val:
        return False
    em = pow(sig_int, e_val, n_val).to_bytes(key_len, "big")
    digest = hashlib.sha256(signing_input).digest()
    t = _SHA256_DIGEST_INFO_PREFIX + digest
    ps_len = key_len - len(t) - 3
    if ps_len < 8:
        return False
    expected_em = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + t
    return hmac.compare_digest(em, expected_em)


def _fetch_jwks(issuer: str, clock: Callable[[], float] = time.time) -> Dict[str, Any]:
    if not issuer.startswith("https://"):
        raise AuthenticationError("Untrusted JWKS issuer scheme.")
    jwks_url = issuer.rstrip("/") + "/.well-known/jwks.json"
    now = clock()
    with _JWKS_CACHE_LOCK:
        cached = _JWKS_CACHE.get(jwks_url)
        if cached and now - cached[0] < _JWKS_TTL_SECONDS:
            return cached[1]

    req = urllib.request.Request(jwks_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:  # nosec B310
            if getattr(resp, "status", 200) != 200:
                raise AuthenticationError("Unable to retrieve JWKS.")
            body = json.loads(resp.read(65_536).decode("utf-8"))
    except (urllib.error.URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthenticationError("Failed to fetch Cognito JWKS.") from exc

    if not isinstance(body, dict) or not isinstance(body.get("keys"), list):
        raise AuthenticationError("Malformed JWKS document.")

    with _JWKS_CACHE_LOCK:
        _JWKS_CACHE[jwks_url] = (now, body)
    return body


def _expected_issuer() -> Optional[str]:
    explicit = os.environ.get("COGNITO_ISSUER", "").strip()
    if explicit:
        return explicit.rstrip("/")
    pool_id = os.environ.get("COGNITO_USER_POOL_ID", "").strip()
    if pool_id:
        region = (
            os.environ.get("COGNITO_REGION")
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "ap-southeast-2"
        ).strip()
        return f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"
    return None


def _expected_client_id() -> Optional[str]:
    val = os.environ.get("COGNITO_CLIENT_ID", "").strip()
    return val or None


def _resolve_jwks(
    expected_issuer: Optional[str],
    override_jwks: Optional[Mapping[str, Any]],
    clock: Callable[[], float],
) -> Optional[Mapping[str, Any]]:
    if override_jwks is not None:
        return override_jwks
    raw = os.environ.get("COGNITO_JWKS_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthenticationError("Invalid JWKS configuration.") from exc
        if isinstance(parsed, dict):
            return parsed
    if expected_issuer and expected_issuer.startswith("https://"):
        return _fetch_jwks(expected_issuer, clock=clock)
    return None


def _audience_matches(claims: Mapping[str, Any], expected_client_id: str) -> bool:
    aud = claims.get("aud")
    client_id = claims.get("client_id")
    if isinstance(aud, str) and hmac.compare_digest(aud, expected_client_id):
        return True
    if isinstance(aud, list) and any(
        isinstance(item, str) and hmac.compare_digest(item, expected_client_id) for item in aud
    ):
        return True
    if isinstance(client_id, str) and hmac.compare_digest(client_id, expected_client_id):
        return True
    return False


def validate_claims(
    claims: Mapping[str, Any],
    *,
    expected_issuer: Optional[str] = None,
    expected_client_id: Optional[str] = None,
    clock: Callable[[], float] = time.time,
    extra_scopes: Optional[Iterable[str]] = None,
) -> AuthContext:
    """Validate required JWT claims and construct an immutable AuthContext."""

    if not isinstance(claims, Mapping):
        raise AuthenticationError("JWT claims missing.")

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise AuthenticationError("Token missing subject claim.")
    sub_clean = _sanitize_identifier(sub)

    now = float(clock())
    exp = claims.get("exp")
    if exp is None or isinstance(exp, bool):
        raise AuthenticationError("Token missing expiration.")
    try:
        exp_ts = float(exp)
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("Token expiration is invalid.") from exc
    if exp_ts <= now - 30.0:
        raise AuthenticationError("Token has expired.")

    nbf = claims.get("nbf")
    if nbf is not None and not isinstance(nbf, bool):
        try:
            nbf_ts = float(nbf)
        except (TypeError, ValueError) as exc:
            raise AuthenticationError("Token nbf claim is invalid.") from exc
        if nbf_ts > now + 30.0:
            raise AuthenticationError("Token is not yet valid.")

    issuer = str(claims.get("iss") or "").rstrip("/")
    if expected_issuer:
        if not hmac.compare_digest(issuer, expected_issuer.rstrip("/")):
            raise AuthenticationError("Untrusted token issuer.")
    elif not issuer:
        raise AuthenticationError("Token missing issuer.")

    client_id = str(claims.get("client_id") or claims.get("aud") or "")
    if expected_client_id and not _audience_matches(claims, expected_client_id):
        raise AuthenticationError("Invalid token audience or client_id.")

    token_use = str(claims.get("token_use") or "id").strip().lower()
    if token_use not in {"id", "access"}:
        raise AuthenticationError("Unsupported Cognito token_use.")

    roles_set = set()
    groups = claims.get("cognito:groups")
    if isinstance(groups, list):
        roles_set.update(str(g).strip().lower() for g in groups if isinstance(g, str) and g.strip())
    elif isinstance(groups, str) and groups.strip():
        cleaned_groups = groups.strip().strip("[]")
        for g in re.split(r"[\s,]+", cleaned_groups):
            if g.strip():
                roles_set.add(g.strip().lower())

    for key in ("custom:role", "role"):
        val = claims.get(key)
        if isinstance(val, str) and val.strip():
            roles_set.add(val.strip().lower())

    explicit_roles = claims.get("roles")
    if isinstance(explicit_roles, list):
        roles_set.update(
            str(r).strip().lower() for r in explicit_roles if isinstance(r, str) and r.strip()
        )

    scopes_set = set()
    raw_scope = claims.get("scope")
    if isinstance(raw_scope, str):
        scopes_set.update(s.strip() for s in raw_scope.split() if s.strip())
    elif isinstance(raw_scope, list):
        scopes_set.update(str(s).strip() for s in raw_scope if isinstance(s, str) and s.strip())
    if extra_scopes:
        scopes_set.update(str(s).strip() for s in extra_scopes if isinstance(s, str) and s.strip())

    # Tenant isolation priority: custom:tenant_id -> tenant_id -> tenant:<id> group -> per-user isolation
    raw_tenant = claims.get("custom:tenant_id") or claims.get("tenant_id")
    tenant_id = ""
    if isinstance(raw_tenant, str) and raw_tenant.strip():
        tenant_id = _sanitize_identifier(raw_tenant)
    else:
        for role in sorted(roles_set):
            if role.startswith("tenant:") and len(role) > 7:
                tenant_id = _sanitize_identifier(role.split(":", 1)[1])
                break
    if not tenant_id:
        tenant_id = f"user:{sub_clean}"

    return AuthContext(
        sub=sub_clean,
        tenant_id=tenant_id,
        roles=frozenset(roles_set),
        scopes=frozenset(scopes_set),
        token_use=token_use,
        issuer=issuer,
        client_id=client_id,
    )


def verify_jwt_hs256(
    token: str,
    secret: str,
    *,
    expected_issuer: Optional[str] = None,
    expected_client_id: Optional[str] = None,
    clock: Callable[[], float] = time.time,
) -> AuthContext:
    if not secret:
        raise AuthenticationError("HMAC verification key is not configured.")
    header, claims, signing_input, signature = _parse_jwt_parts(token)
    if header.get("alg") != "HS256":
        raise AuthenticationError("Unsupported JWT algorithm.")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_sig):
        raise AuthenticationError("Invalid JWT signature.")
    return validate_claims(
        claims,
        expected_issuer=expected_issuer,
        expected_client_id=expected_client_id,
        clock=clock,
    )


def verify_jwt_rs256(
    token: str,
    jwks: Mapping[str, Any],
    *,
    expected_issuer: Optional[str] = None,
    expected_client_id: Optional[str] = None,
    clock: Callable[[], float] = time.time,
) -> AuthContext:
    header, claims, signing_input, signature = _parse_jwt_parts(token)
    if header.get("alg") != "RS256":
        raise AuthenticationError("Unsupported JWT algorithm.")
    kid = header.get("kid")
    keys = jwks.get("keys") if isinstance(jwks, Mapping) else None
    if not isinstance(keys, list) or not keys:
        raise AuthenticationError("No JWKS keys available.")

    matching = [
        k for k in keys if isinstance(k, Mapping) and (not kid or k.get("kid") == kid)
    ]
    if not matching:
        raise AuthenticationError("Signing key ID not found.")
    if not any(_verify_rs256_signature(signing_input, signature, k) for k in matching):
        raise AuthenticationError("Invalid JWT signature.")

    return validate_claims(
        claims,
        expected_issuer=expected_issuer,
        expected_client_id=expected_client_id,
        clock=clock,
    )


def verify_bearer_token(
    token: str,
    *,
    expected_issuer: Optional[str] = None,
    expected_client_id: Optional[str] = None,
    jwks: Optional[Mapping[str, Any]] = None,
    hmac_secret: Optional[str] = None,
    clock: Callable[[], float] = time.time,
) -> AuthContext:
    header, _, _, _ = _parse_jwt_parts(token)
    alg = header.get("alg")
    if not isinstance(alg, str) or alg.lower() == "none":
        raise AuthenticationError("Unsigned JWT tokens are rejected.")

    if alg == "RS256":
        resolved_jwks = _resolve_jwks(expected_issuer, jwks, clock)
        if resolved_jwks is None:
            raise AuthenticationError("Cognito JWKS is not configured.")
        return verify_jwt_rs256(
            token,
            resolved_jwks,
            expected_issuer=expected_issuer,
            expected_client_id=expected_client_id,
            clock=clock,
        )

    if alg == "HS256":
        secret = hmac_secret if hmac_secret is not None else os.environ.get("JWT_HMAC_SECRET", "")
        if not secret:
            raise AuthenticationError("HS256 token verification is not enabled.")
        return verify_jwt_hs256(
            token,
            secret,
            expected_issuer=expected_issuer,
            expected_client_id=expected_client_id,
            clock=clock,
        )

    raise AuthenticationError("Unsupported JWT algorithm.")


def authenticate_event(
    event: Mapping[str, Any],
    *,
    clock: Callable[[], float] = time.time,
    jwks: Optional[Mapping[str, Any]] = None,
    hmac_secret: Optional[str] = None,
) -> AuthContext:
    """Authenticate an API Gateway v2 event via Cognito JWT or edge authorizer claims."""

    expected_issuer = _expected_issuer()
    expected_client_id = _expected_client_id()
    raw_token = extract_bearer_token(event.get("headers"))

    request_ctx = event.get("requestContext") or {}
    authorizer = request_ctx.get("authorizer") if isinstance(request_ctx, Mapping) else None
    jwt_ctx = authorizer.get("jwt") if isinstance(authorizer, Mapping) else None
    apigw_claims = jwt_ctx.get("claims") if isinstance(jwt_ctx, Mapping) else None
    apigw_scopes = jwt_ctx.get("scopes") if isinstance(jwt_ctx, Mapping) else None

    if isinstance(apigw_claims, Mapping) and apigw_claims:
        ctx = validate_claims(
            apigw_claims,
            expected_issuer=expected_issuer,
            expected_client_id=expected_client_id,
            clock=clock,
            extra_scopes=apigw_scopes if isinstance(apigw_scopes, list) else None,
        )
        # If raw Bearer header is also present, ensure it binds to the same subject.
        if raw_token is not None:
            _, raw_claims, _, _ = _parse_jwt_parts(raw_token)
            if str(raw_claims.get("sub") or "").strip() and _sanitize_identifier(
                str(raw_claims["sub"])
            ) != ctx.sub:
                raise AuthenticationError("Bearer token mismatch with authorizer context.")
            # If local verification material is explicitly configured, verify signature too.
            if jwks is not None or os.environ.get("COGNITO_JWKS_JSON") or (
                hmac_secret or os.environ.get("JWT_HMAC_SECRET")
            ):
                return verify_bearer_token(
                    raw_token,
                    expected_issuer=expected_issuer,
                    expected_client_id=expected_client_id,
                    jwks=jwks,
                    hmac_secret=hmac_secret,
                    clock=clock,
                )
        return ctx

    if raw_token is not None:
        return verify_bearer_token(
            raw_token,
            expected_issuer=expected_issuer,
            expected_client_id=expected_client_id,
            jwks=jwks,
            hmac_secret=hmac_secret,
            clock=clock,
        )

    raise AuthenticationError("Authentication required.")


def authorize_triage(ctx: AuthContext) -> None:
    """Ensure caller is authorized to invoke POST /triage."""

    required = os.environ.get("REQUIRED_TRIAGE_SCOPE", "").strip()
    if required:
        if required not in ctx.scopes and not (ctx.roles & _ADMIN_ROLES):
            raise AuthorizationError("Insufficient scope for ticket triage.")
        return

    # Check OAuth token_use claim name (not a password literal).
    if ctx.token_use == "access" and ctx.scopes:  # nosec B105
        if not (ctx.scopes & _TRIAGE_SCOPES) and not (ctx.roles & _ADMIN_ROLES):
            raise AuthorizationError("Insufficient scope for ticket triage.")


def authorize_stats(ctx: AuthContext) -> None:
    """Enforce administrative RBAC for GET /stats."""

    if (ctx.roles & _ADMIN_ROLES) or (ctx.scopes & _ADMIN_SCOPES):
        return
    raise AuthorizationError("Administrator role required for stats endpoint.")


def enforce_no_body_identity_spoofing(body: Mapping[str, Any], ctx: AuthContext) -> None:
    """Reject untrusted identity or tenant assertions inside request payloads."""

    if not isinstance(body, Mapping):
        return
    for key in body:
        if isinstance(key, str) and key.lower() in _IDENTITY_SPOOF_FIELDS:
            if key.lower() == "tenant_id" and str(body[key]).strip() == ctx.tenant_id:
                continue
            raise AuthorizationError("Identity and tenant attributes cannot be supplied in body.")
