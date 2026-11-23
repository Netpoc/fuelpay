"""Admin accounts (owners only) and the audit log."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_schemas import AdminCreate, AdminOut, AdminUpdate, AuditOut, AuditPage
from app.db import get_session
from app.models.entities import AdminAuditLog, AdminRole, AdminSession, AdminUser
from app.services.admin_auth import (
    AdminActor,
    audit,
    create_admin,
    hash_password,
    password_problem,
    require_owner,
    require_platform_admin,
)

router = APIRouter()


@router.get("/admins", response_model=list[AdminOut], summary="List admins")
async def list_admins(
    _: AdminActor = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> list[AdminUser]:
    return list((await session.execute(select(AdminUser).order_by(AdminUser.created_at))).scalars())


@router.post(
    "/admins", response_model=AdminOut, status_code=status.HTTP_201_CREATED, summary="Add an admin"
)
async def add_admin(
    payload: AdminCreate,
    actor: AdminActor = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> AdminUser:
    try:
        user = await create_admin(
            session, payload.email, payload.name, payload.password, payload.role
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An admin with that email already exists."
        ) from None
    await audit(
        session,
        actor,
        "admin.create",
        "admin",
        user.id,
        {"email": user.email, "role": user.role.value},
    )
    await session.refresh(user)
    return user


async def _active_owners(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(AdminUser)
                .where(AdminUser.role == AdminRole.OWNER, AdminUser.is_active.is_(True))
            )
        ).scalar_one()
    )


@router.patch("/admins/{admin_id}", response_model=AdminOut, summary="Change an admin")
async def update_admin(
    admin_id: uuid.UUID,
    payload: AdminUpdate,
    actor: AdminActor = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> AdminUser:
    user = await session.get(AdminUser, admin_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found.")

    demoting = payload.role == AdminRole.STAFF or payload.is_active is False
    if (
        demoting
        and user.role == AdminRole.OWNER
        and user.is_active
        and await _active_owners(session) <= 1
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This is the last active owner. Make someone else an owner first.",
        )

    changes: dict = {}
    if payload.name is not None:
        user.name, changes["name"] = payload.name.strip(), payload.name.strip()
    if payload.role is not None:
        user.role, changes["role"] = payload.role, payload.role.value
    if payload.is_active is not None:
        user.is_active, changes["is_active"] = payload.is_active, payload.is_active
    if payload.password is not None:
        problem = password_problem(payload.password)
        if problem:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)
        user.password_hash = hash_password(payload.password)
        changes["password"] = "reset"
    # Deactivation or a password reset signs the person out everywhere.
    if payload.is_active is False or payload.password is not None:
        await session.execute(delete(AdminSession).where(AdminSession.admin_user_id == user.id))

    await audit(session, actor, "admin.update", "admin", user.id, {"email": user.email, **changes})
    await session.flush()
    return user


@router.get("/audit", response_model=AuditPage, summary="Audit log, newest first")
async def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    before: datetime | None = Query(default=None, description="Keyset cursor."),
    action: str | None = Query(default=None, max_length=80, description="Prefix, e.g. 'tenant.'"),
    _: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> AuditPage:
    query = select(AdminAuditLog)
    if before is not None:
        query = query.where(AdminAuditLog.at < before)
    if action:
        query = query.where(AdminAuditLog.action.startswith(action))
    rows = list(
        (await session.execute(query.order_by(AdminAuditLog.at.desc()).limit(limit + 1))).scalars()
    )
    page = rows[:limit]
    return AuditPage(
        items=[AuditOut.model_validate(r) for r in page],
        next_cursor=page[-1].at if len(rows) > limit and page else None,
    )
