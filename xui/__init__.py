from aiogram import Router

from xui.admin import router as admin_router
from xui.paid_subscriptions import router as paid_subscriptions_router
from xui.vpn import router as vpn_router

router = Router()
router.include_router(admin_router)
router.include_router(paid_subscriptions_router)
router.include_router(vpn_router)
