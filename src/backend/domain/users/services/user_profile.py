from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.domain.users.models.user import User
from backend.domain.users.models.user_profile import UserProfile
from backend.domain.users.schemas.user_profile import (
    UserProfileCreate,
    UserProfileUpdate,
)


class UserProfileService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_profile(self, current_user: User) -> UserProfile:
        if current_user.profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="유저 프로필을 찾을 수 없습니다.",
            )
        return current_user.profile

    def create_profile(
        self, current_user: User, body: UserProfileCreate
    ) -> UserProfile:
        if current_user.profile is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="유저 프로필이 이미 존재합니다.",
            )

        profile = UserProfile(
            user=current_user,
            nickname=body.nickname,
            activity_type=(
                body.activity_type.value if body.activity_type is not None else None
            ),
        )
        self.db.add(profile)
        self._commit()
        self.db.refresh(profile)
        return profile

    def update_profile(
        self, current_user: User, body: UserProfileUpdate
    ) -> UserProfile:
        profile = self.get_profile(current_user)
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="수정할 프로필 항목이 없습니다.",
            )

        for field, value in changes.items():
            if field == "activity_type" and value is not None:
                value = value.value
            setattr(profile, field, value)

        self._commit()
        self.db.refresh(profile)
        return profile

    def withdraw(self, current_user: User) -> None:
        self.db.delete(current_user)
        self._commit()

    def _commit(self) -> None:
        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise
