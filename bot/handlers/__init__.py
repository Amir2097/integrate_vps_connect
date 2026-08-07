from aiogram import Router
from .admin import router as admin_router
from .user import router as user_router

router = Router()
router.include_router(admin_router)
router.include_router(user_router)
