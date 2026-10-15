from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

InterestCategory = Literal[
    "소프트웨어·AI",
    "헬스케어",
    "교육",
    "금융",
    "환경·에너지",
    "식품·농업",
    "커머스·유통",
    "제조·로봇",
    "모빌리티·물류",
    "콘텐츠·미디어",
    "관광·여가",
    "기타",
]
FocusItem = Annotated[str, Field(min_length=1, max_length=120)]
IdeaDetail = Annotated[str, Field(min_length=1, max_length=500)]


class APIErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class APIErrorResponse(BaseModel):
    error: APIErrorDetail


class IdeaGenerationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=5000)
    source_file_ids: list[UUID] = Field(default_factory=list, max_length=10)
    project_id: UUID | None = None

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("프롬프트는 공백일 수 없습니다.")
        if len(normalized) < 2:
            raise ValueError("프롬프트는 2자 이상이어야 합니다.")
        return normalized

    @field_validator("source_file_ids")
    @classmethod
    def reject_duplicate_source_files(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("참조 파일 ID는 중복될 수 없습니다.")
        return value


class SourceFileReference(BaseModel):
    id: UUID
    filename: str
    media_type: str


class SourceFileUploadResponse(SourceFileReference):
    size_bytes: int
    status: Literal["ready"]


class IdeaSuggestionResponse(BaseModel):
    id: str
    title: str = Field(min_length=1, max_length=200)
    details: list[IdeaDetail] = Field(min_length=1, max_length=4)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("아이디어 제목은 비어 있을 수 없습니다.")
        return normalized

    @field_validator("details")
    @classmethod
    def details_must_not_be_blank(cls, value: list[IdeaDetail]) -> list[IdeaDetail]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("아이디어 설명은 비어 있을 수 없습니다.")
        return normalized


class IdeaGenerationContext(BaseModel):
    source_files: list[SourceFileReference]
    focus_items: list[FocusItem] = Field(min_length=1, max_length=8)


class IdeaGenerationResponse(BaseModel):
    generation_id: UUID
    created_at: datetime
    context: IdeaGenerationContext
    suggestions: list[IdeaSuggestionResponse] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def suggestions_must_be_distinct(self) -> "IdeaGenerationResponse":
        ids = [suggestion.id for suggestion in self.suggestions]
        titles = [suggestion.title.casefold() for suggestion in self.suggestions]
        if len(ids) != len(set(ids)) or len(titles) != len(set(titles)):
            raise ValueError("아이디어는 서로 다른 제목과 ID를 가져야 합니다.")
        return self


class IdeaSelectionRequest(BaseModel):
    selected_idea_id: UUID


class IdeaSelectionResponse(BaseModel):
    generation_id: UUID
    selected_idea_id: UUID
    selected_at: datetime
