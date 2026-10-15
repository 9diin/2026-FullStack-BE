"""아이디어 구체화(Elaboration) 요청/응답 Pydantic 스키마

스펙 문서 Section 4.1의 TypeScript 인터페이스를 Python Pydantic 으로 구현합니다.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

# 페르소나 근거 포인트: 20~25자 제한 (스펙 2.2 참조)
EvidencePoint = Annotated[str, Field(min_length=20, max_length=25)]


class TargetPersona(BaseModel):
    """핵심 타깃 페르소나 정의"""

    title: str = Field(min_length=1, max_length=100, description="페르소나 명칭")
    description: str = Field(min_length=1, max_length=500, description="페르소나 상세 설명")
    evidence_points: tuple[EvidencePoint, EvidencePoint, EvidencePoint] = Field(
        description="페인포인트 근거 3가지 (각 20~25자)"
    )

    @field_validator("evidence_points", mode="before")
    @classmethod
    def validate_evidence_points_length(
        cls, value: list[str] | tuple[str, ...]
    ) -> tuple[str, str, str]:
        items = list(value)
        if len(items) != 3:
            raise ValueError("페르소나 근거는 정확히 3개여야 합니다.")
        return tuple(items)  # type: ignore[return-value]


class PainPointCycleStep(BaseModel):
    """3대 페인포인트 악순환 고리 단계"""

    step: str = Field(description="단계 표기 (예: 단계 ①)")
    step_name: str = Field(min_length=1, max_length=20, description="단계명 (예: 강제구매)")
    title: str = Field(min_length=1, max_length=50, description="핵심 타이틀")
    description: str = Field(min_length=1, max_length=200, description="세부 디스크립션")
    highlight_tag: str = Field(min_length=1, max_length=50, description="결과/수치 라벨")


class AICoaching(BaseModel):
    """실시간 AI 검증 피드백 코칭"""

    solution_evidence: str = Field(
        min_length=100,
        description="종합 도출 솔루션 상세 근거 문장 (300자 이상 권장)",
    )
    feedback_review: str = Field(
        min_length=50,
        description="확장된 심사위원 코칭 피드백 문장 (150자 이상 권장)",
    )


# ─── 요청 스키마 ──────────────────────────────────────────────────────────────

class ElaborationRequest(BaseModel):
    """POST /idea-generations/{generation_id}/elaboration 요청 바디

    프런트엔드 Alert Dialog에서 '확인' 클릭 시 전송되는 데이터입니다.
    selected_idea_id를 기반으로 LLM이 구체화 데이터를 자동 생성하거나,
    직접 전달된 데이터를 저장합니다.
    """

    selected_idea_id: UUID = Field(description="구체화할 아이디어 제안 ID")
    title: str | None = Field(
        default=None, min_length=1, max_length=400, description="아이디어 구체화 제목 (미입력 시 LLM 자동 생성)"
    )
    summary: str | None = Field(
        default=None,
        min_length=100,
        description="문제인식 상세 문장 (미입력 시 LLM 자동 생성)",
    )
    persona: TargetPersona | None = Field(
        default=None, description="핵심 타깃 페르소나 (미입력 시 LLM 자동 생성)"
    )
    pain_point_cycle: tuple[
        PainPointCycleStep, PainPointCycleStep, PainPointCycleStep
    ] | None = Field(default=None, description="3대 페인포인트 악순환 고리 (미입력 시 LLM 자동 생성)")
    ai_coaching: AICoaching | None = Field(
        default=None, description="실시간 AI 검증 피드백 코칭 (미입력 시 LLM 자동 생성)"
    )

    @field_validator("pain_point_cycle", mode="before")
    @classmethod
    def validate_pain_point_cycle_length(
        cls, value: list | tuple | None,
    ) -> tuple | None:
        if value is None:
            return None
        items = list(value)
        if len(items) != 3:
            raise ValueError("페인포인트 악순환 고리는 정확히 3단계여야 합니다.")
        return tuple(items)  # type: ignore[return-value]

    @model_validator(mode="after")
    def validate_pain_point_cycle_order(self) -> "ElaborationRequest":
        if self.pain_point_cycle is None:
            return self
        expected = ("단계 ①", "단계 ②", "단계 ③")
        for i, step in enumerate(self.pain_point_cycle):
            if step.step != expected[i]:
                raise ValueError(
                    f"페인포인트 {i + 1}단계의 step 값이 '{expected[i]}'이어야 합니다. "
                    f"현재: '{step.step}'"
                )
        return self


# ─── 응답 스키마 ──────────────────────────────────────────────────────────────

class PainPointCycleStepResponse(PainPointCycleStep):
    """응답 전용 페인포인트 단계 (별칭 없이 스네이크 케이스 유지)"""


class ElaborationResponse(BaseModel):
    """POST /idea-generations/{generation_id}/elaboration 응답 바디"""

    elaboration_id: UUID
    generation_id: UUID
    selected_idea_id: UUID
    title: str
    summary: str
    persona: TargetPersona
    pain_point_cycle: tuple[
        PainPointCycleStepResponse,
        PainPointCycleStepResponse,
        PainPointCycleStepResponse,
    ]
    ai_coaching: AICoaching
    created_at: datetime
