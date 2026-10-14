from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ActivityType(str, Enum):
    PROSPECTIVE_FOUNDER = "예비창업가"
    STARTUP_FOUNDER = "스타트업 대표"
    STARTUP_MEMBER = "창업 멤버"
    STUDENT_OR_RESEARCHER = "학생 및 연구자"
    INVESTOR_OR_MENTOR = "투자자 및 멘토"


class UserProfileCreate(BaseModel):
    nickname: str | None = Field(default=None, max_length=50)
    activity_type: ActivityType | None = None

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("닉네임은 공백일 수 없습니다.")
        return normalized


class UserProfileUpdate(UserProfileCreate):
    pass


class UserProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str | None
    activity_type: ActivityType | None
    created_at: datetime
    updated_at: datetime
