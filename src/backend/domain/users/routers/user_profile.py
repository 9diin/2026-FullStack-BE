from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.domain.users.models.user import User
from backend.domain.users.routers.dependencies import get_current_user
from backend.domain.users.schemas.user_profile import (
    UserProfileCreate,
    UserProfileRead,
    UserProfileUpdate,
)
from backend.domain.users.services.user_profile import UserProfileService

router = APIRouter(prefix="/user", tags=["USER"])


def get_user_profile_service(db: Session = Depends(get_db)) -> UserProfileService:
    return UserProfileService(db)


@router.get("/profile", response_model=UserProfileRead)
def get_user_profile(
    current_user: User = Depends(get_current_user),
    profile_service: UserProfileService = Depends(get_user_profile_service),
) -> UserProfileRead:
    return profile_service.get_profile(current_user)


@router.post(
    "/profile",
    response_model=UserProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_user_profile(
    body: UserProfileCreate,
    current_user: User = Depends(get_current_user),
    profile_service: UserProfileService = Depends(get_user_profile_service),
) -> UserProfileRead:
    return profile_service.create_profile(current_user, body)


@router.patch("/profile", response_model=UserProfileRead)
def update_user_profile(
    body: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    profile_service: UserProfileService = Depends(get_user_profile_service),
) -> UserProfileRead:
    return profile_service.update_profile(current_user, body)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def withdraw_user(
    current_user: User = Depends(get_current_user),
    profile_service: UserProfileService = Depends(get_user_profile_service),
) -> None:
    profile_service.withdraw(current_user)
