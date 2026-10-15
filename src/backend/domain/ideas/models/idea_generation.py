from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base


class SourceFile(Base):
    __tablename__ = "idea_source_files"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class IdeaGeneration(Base):
    __tablename__ = "idea_generations"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    interest_categories: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    suggestions: Mapped[list["IdeaSuggestion"]] = relationship(
        back_populates="generation",
        cascade="all, delete-orphan",
        order_by="IdeaSuggestion.position",
    )


class IdeaSuggestion(Base):
    __tablename__ = "idea_suggestions"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("idea_generations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    selected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generation: Mapped[IdeaGeneration] = relationship(back_populates="suggestions")


class IdeaSelectionEvent(Base):
    __tablename__ = "idea_selection_events"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("idea_generations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    suggestion_id: Mapped[UUID] = mapped_column(
        ForeignKey("idea_suggestions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class IdeaElaboration(Base):
    """아이디어 구체화 데이터 - 문제인식/페르소나/페인포인트/AI코칭을 저장합니다."""

    __tablename__ = "idea_elaborations"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    generation_id: Mapped[UUID] = mapped_column(
        ForeignKey("idea_generations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,  # 1 generation : 1 elaboration
    )
    suggestion_id: Mapped[UUID] = mapped_column(
        ForeignKey("idea_suggestions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 구체화 제목 (선택된 아이디어 제목)
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    # 문제인식 상세 문장 (요약문 대비 약 2배 분량)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # 핵심 타깃 페르소나 (JSON): {title, description, evidence_points: [str, str, str]}
    persona: Mapped[dict] = mapped_column(JSON, nullable=False)
    # 3대 페인포인트 악순환 고리 (JSON): [{step, step_name, title, description, highlight_tag}, ...]
    pain_point_cycle: Mapped[list] = mapped_column(JSON, nullable=False)
    # AI 솔루션 종합 근거 문장
    solution_evidence: Mapped[str] = mapped_column(Text, nullable=False)
    # AI 평가위원 코칭 피드백 문장
    feedback_review: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
