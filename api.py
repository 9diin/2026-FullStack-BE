# [핵심] 모든 도메인 라우터를 모아주는 중앙 라우터

from fastapi import APIRouter

from backend.domain.users.routers.user import router as users_router

api_router = APIRouter(prefix="/api/v1")

# 각 도메인 라우터 포함시키기
api_router.include_router(users_router)
