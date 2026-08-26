"""
Minimal application auth between the Next.js proxy (Vercel) and this
self-hosted backend.

Transport (Cloudflare Tunnel or equivalent) already protects against
exposing a raw port; this layer verifies that a caller knows the shared
token(s) — good enough for single-user usage.

AEGIS_BACKEND_TOKENS accepts a CSV list to allow token rotation without
downtime (the old and new tokens coexist during the deployment).
"""
import hmac
import os
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status


def _load_tokens() -> set[str]:
    raw = os.getenv("AEGIS_BACKEND_TOKENS", "")
    tokens = {t.strip() for t in raw.split(",") if t.strip()}
    return tokens


def verify_bearer_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    tokens = _load_tokens()
    if not tokens:
        # No token configured: refuse rather than accidentally opening up in the clear.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AEGIS_BACKEND_TOKENS not configured server-side.",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <token> required.",
        )

    presented = authorization.removeprefix("Bearer ").strip()
    if not any(hmac.compare_digest(presented, t) for t in tokens):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )


RequireAuth = Depends(verify_bearer_token)
