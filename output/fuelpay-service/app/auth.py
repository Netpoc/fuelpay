"""API-key authentication and tenant scoping.

Every request resolves to exactly one Organisation, and every query in the API
layer filters on that organisation's id. Tenant isolation is enforced in the
query, not by trusting an id supplied in the path — a caller can name any UUID
they like, but they will only ever match rows in their own tenant.

Keys are stored as SHA-256 hashes. The plaintext is shown once, at issue, and
is unrecoverable afterwards. SHA-256 rather than a slow KDF is deliberate:
these are high-entropy machine-generated tokens, not user-chosen passwords, so
brute force is infeasible regardless and the check sits on every request.

Demo tenants (opened with a coupon) authenticate the same way but stop
resolving the moment `demo_expires_at` passes, even if the expiry job that
revokes their keys has not run yet.

The platform API (`/v1/platform`) sits outside tenancy altogether; its
admins authenticate in `app.services.admin_auth`, never with a tenant key.
"""

import hashlib
import secrets
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.entities import ApiKey, Organisation

KEY_PREFIX = "fp_"
PREFIX_LENGTH = 12


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def generate_key() -> tuple[str, str, str]:
    """Mint a key. Returns (plaintext, hash, display prefix)."""
    plaintext = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return plaintext, hash_key(plaintext), plaintext[:PREFIX_LENGTH]


def _extract(api_key_header: str | None, authorization: str | None) -> str | None:
    """Accept either `X-API-Key: <key>` or `Authorization: Bearer <key>`."""
    if api_key_header:
        return api_key_header.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def require_organisation(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Organisation:
    """Resolve the caller's organisation, or reject the request."""
    plaintext = _extract(x_api_key, authorization)
    if not plaintext:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Send X-API-Key or Authorization: Bearer <key>.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await session.execute(
        select(Organisation)
        .join(ApiKey, ApiKey.organisation_id == Organisation.id)
        .where(
            ApiKey.key_hash == hash_key(plaintext),
            ApiKey.revoked_at.is_(None),
            or_(
                Organisation.is_demo.is_(False),
                Organisation.demo_expires_at > datetime.now(UTC),
            ),
        )
    )
    organisation = result.scalar_one_or_none()

    if organisation is None:
        # Deliberately does not distinguish unknown from revoked (or from an
        # expired demo): that difference is information an attacker can use.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return organisation


async def require_full_tenant(
    organisation: Organisation = Depends(require_organisation),
) -> Organisation:
    """A tenant that is not a demo.

    Guards the simulator controls: `/admin/tick` advances every tenant's
    clock, and the incident injectors exist for staged sales demos, not for a
    prospect to manufacture thefts in their own sandbox.
    """
    if organisation.is_demo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not available on a demo account.",
        )
    return organisation
