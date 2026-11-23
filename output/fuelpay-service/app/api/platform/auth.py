"""Admin sign-in. The only unauthenticated routes under /v1/platform."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_schemas import AdminOut, LoginOut, LoginRequest, MeOut
from app.db import get_session
from app.models.entities import AdminSession, AdminUser
from app.ratelimit import SlidingWindowLimiter
from app.services.admin_auth import (
    AdminActor,
    audit,
    authenticate,
    open_session,
    require_platform_admin,
)
from app.services.provisioning import hash_ip

router = APIRouter(prefix="/auth")

# Per source address and per account, so neither a spray across accounts nor
# a focused guess at one account gets more than a handful of tries a minute.
_by_ip = SlidingWindowLimiter(10, 60.0)
_by_email = SlidingWindowLimiter(5, 60.0)


@router.post("/login", response_model=LoginOut, summary="Sign in to the admin console")
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LoginOut:
    ip = request.client.host if request.client else "unknown"
    email = payload.email.strip().lower()
    if not _by_ip.allow(ip) or not _by_email.allow(email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts. Try again in a minute.",
        )

    user = await authenticate(session, email, payload.password)
    if user is None:
        # One message for unknown email, wrong password and disabled account.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect."
        )

    token, row = await open_session(session, user, hash_ip(ip))
    actor = AdminActor(label=user.email, role=user.role, user_id=user.id, session_id=row.id)
    await audit(session, actor, "admin.login", "admin", user.id)
    return LoginOut(token=token, expires_at=row.expires_at, admin=AdminOut.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End this session")
async def logout(
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    if actor.session_id is not None:
        await session.execute(delete(AdminSession).where(AdminSession.id == actor.session_id))


@router.get("/me", response_model=MeOut, summary="Who is signed in")
async def me(
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    if actor.user_id is None:
        return MeOut(
            admin=AdminOut(email=actor.label, name="Break-glass key", role=actor.role),
            break_glass=True,
        )
    user = await session.get(AdminUser, actor.user_id)
    return MeOut(admin=AdminOut.model_validate(user))
