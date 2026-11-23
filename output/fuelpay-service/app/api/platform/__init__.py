"""Operator API, `/v1/platform`: everything the admin console does.

Sits outside tenancy. Every route except login requires a signed-in admin
(or the break-glass key); routes that change platform-wide behaviour or other
admins require an OWNER. Every change writes an audit row in the same
transaction as the change itself.
"""

from fastapi import APIRouter

from app.api.platform import admins, auth, coupons, overview, system, tenants

router = APIRouter(prefix="/v1/platform", tags=["platform"])
router.include_router(auth.router)
router.include_router(coupons.router)
router.include_router(tenants.router)
router.include_router(overview.router)
router.include_router(system.router)
router.include_router(admins.router)

__all__ = ["router"]
