"""Platform-admin identity: passwords, sessions, and the audit trail.

Admins are people who operate the platform, not tenant users. They sign in
with email and password and get a session token, sent back on each request as
`X-Admin-Token`. As with API keys, only the token's SHA-256 is stored.

Passwords use scrypt from the standard library. Unlike API keys, these are
human-chosen and low-entropy, so a deliberately slow, salted KDF is the right
tool here where SHA-256 is right for keys.

The `FUELPAY_PLATFORM_ADMIN_KEY` from configuration still works as a
break-glass credential, for scripts and for creating the first admin. It acts
as an OWNER and is audited under its own label.
"""

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_key
from app.config import Settings, get_settings
from app.db import get_session
from app.models.entities import AdminAuditLog, AdminRole, AdminSession, AdminUser

SESSION_TTL = timedelta(hours=12)
TOKEN_PREFIX = "fpa_"
BREAK_GLASS_LABEL = "break-glass key"
MIN_PASSWORD_LENGTH = 10

# scrypt cost: n=2^15, r=8, p=1 (~32 MiB, tens of ms) — OWASP's floor for
# scrypt, and slow enough that an offline guess costs real money.
_N, _R, _P, _DKLEN = 2**15, 8, 1, 32
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    """`scrypt$n$r$p$salt$hash`, all parameters stored so they can be raised later."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM
    )
    encode = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${encode(salt)}${encode(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# A real hash of nothing, verified against when the email is unknown, so a
# missing account costs as long to reject as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Passwords need at least {MIN_PASSWORD_LENGTH} characters."
    if password.lower() == password or password.upper() == password:
        if not any(ch.isdigit() for ch in password):
            return "Mix upper- and lower-case letters, or add a number."
    return None


@dataclass(frozen=True)
class AdminActor:
    """Who is making a platform request: a signed-in admin, or the break-glass key."""

    label: str
    role: AdminRole
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None

    @property
    def is_owner(self) -> bool:
        return self.role == AdminRole.OWNER


BREAK_GLASS = AdminActor(label=BREAK_GLASS_LABEL, role=AdminRole.OWNER)


async def authenticate(session: AsyncSession, email: str, password: str) -> AdminUser | None:
    """The active admin these credentials belong to, or None."""
    user = (
        await session.execute(select(AdminUser).where(AdminUser.email == email.strip().lower()))
    ).scalar_one_or_none()
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash) or not user.is_active:
        return None
    return user


async def open_session(
    session: AsyncSession, user: AdminUser, ip_hash: str | None, now: datetime | None = None
) -> tuple[str, AdminSession]:
    """Mint a session. Returns (plaintext token, row). Does not commit."""
    now = now or datetime.now(UTC)
    token = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    row = AdminSession(
        id=uuid.uuid4(),
        admin_user_id=user.id,
        token_hash=hash_key(token),
        ip_hash=ip_hash,
        expires_at=now + SESSION_TTL,
        last_seen_at=now,
    )
    session.add(row)
    user.last_login_at = now
    await session.flush()
    return token, row


async def resolve_session(
    session: AsyncSession, token: str, now: datetime | None = None
) -> AdminActor | None:
    now = now or datetime.now(UTC)
    row = (
        await session.execute(
            select(AdminSession, AdminUser)
            .join(AdminUser, AdminUser.id == AdminSession.admin_user_id)
            .where(
                AdminSession.token_hash == hash_key(token),
                AdminSession.expires_at > now,
                AdminUser.is_active.is_(True),
            )
        )
    ).first()
    if row is None:
        return None
    admin_session, user = row
    admin_session.last_seen_at = now
    return AdminActor(
        label=user.email, role=user.role, user_id=user.id, session_id=admin_session.id
    )


async def audit(
    session: AsyncSession,
    actor: AdminActor,
    action: str,
    target_type: str | None = None,
    target_id: object = None,
    detail: dict | None = None,
) -> None:
    """Record a platform change. Written in the same transaction as the change,
    so a rolled-back action leaves no audit row and a committed one always does."""
    session.add(
        AdminAuditLog(
            id=uuid.uuid4(),
            admin_user_id=actor.user_id,
            actor_label=actor.label,
            action=action,
            target_type=target_type,
            target_id=None if target_id is None else str(target_id),
            detail=detail or {},
        )
    )


async def create_admin(
    session: AsyncSession, email: str, name: str, password: str, role: AdminRole
) -> AdminUser:
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    user = AdminUser(
        id=uuid.uuid4(),
        email=email.strip().lower(),
        name=name.strip(),
        password_hash=hash_password(password),
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def require_platform_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminActor:
    """A signed-in admin (`X-Admin-Token`), or the break-glass key from
    configuration (`X-Admin-Token` or `X-API-Key`, for existing scripts).

    A tenant's API key never resolves here: tenant keys are looked up in
    `api_keys`, admin sessions in `admin_sessions`, and the two never meet.
    """
    presented = (x_admin_token or x_api_key or "").strip()
    expected = settings.platform_admin_key
    if expected and presented and hmac.compare_digest(presented.encode(), expected.encode()):
        return BREAK_GLASS
    if x_admin_token:
        actor = await resolve_session(session, x_admin_token.strip())
        if actor is not None:
            return actor
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in to the admin console.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_owner(actor: AdminActor = Depends(require_platform_admin)) -> AdminActor:
    if not actor.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owners only.")
    return actor
