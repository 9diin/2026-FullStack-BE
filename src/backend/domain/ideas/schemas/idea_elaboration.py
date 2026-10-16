"""아이디어 구체화(Elaboration) 요청/응답 Pydantic 스키마

스펙 문서 Section 4.1의 TypeScript 인터페이스를 Python Pydantic 으로 구현합니다.
"""

from datetime import datetime
from typing import Annotated, Literal
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

    pain_point_id: UUID
    order: int = Field(ge=1, le=3)


MetricStatus = Literal["measured", "target", "estimate", "unknown"]


class SolutionMetric(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    value: float | int | str | None = None
    unit: str | None = Field(default=None, max_length=30)
    status: MetricStatus
    basis: str | None = Field(default=None, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_evidence(self) -> "SolutionMetric":
        if self.status == "unknown":
            if self.value is not None:
                raise ValueError("미확인 지표의 value는 null이어야 합니다.")
        elif self.value is None:
            raise ValueError("확인 또는 목표 지표에는 value가 필요합니다.")
        if self.value is not None and not self.basis and not self.evidence_ids:
            raise ValueError("수치 지표에는 근거 또는 명시적인 산출 기준이 필요합니다.")
        return self


class SolutionValidation(BaseModel):
    status: MetricStatus
    score: float | None = Field(default=None, ge=0, le=100)
    label: str = Field(min_length=1, max_length=100)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_score_evidence(self) -> "SolutionValidation":
        if self.status == "unknown" and self.score is not None:
            raise ValueError("검증 상태가 미확인인 경우 score는 null이어야 합니다.")
        if self.score is not None and (
            self.status != "measured" or not self.evidence_ids
        ):
            raise ValueError("검증 점수에는 실측 상태와 근거 ID가 필요합니다.")
        return self


class SolutionPipelineStep(BaseModel):
    solution_step_id: UUID
    order: int = Field(ge=1, le=4)
    category: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=100)
    subtitle: str = Field(min_length=1, max_length=150)
    description: str = Field(min_length=1, max_length=1000)
    technology_label: str = Field(min_length=1, max_length=80)
    addresses_pain_point_ids: list[UUID] = Field(min_length=1, max_length=3)
    metrics: list[SolutionMetric] = Field(default_factory=list, max_length=10)


class SolutionComparisonItem(BaseModel):
    item_id: UUID
    text: str = Field(min_length=1, max_length=500)
    pain_point_ids: list[UUID] = Field(min_length=1, max_length=3)


class SolutionToBeItem(SolutionComparisonItem):
    solution_step_ids: list[UUID] = Field(min_length=1, max_length=4)


class SolutionComparisonSide(BaseModel):
    label: Literal["AS-IS"]
    metrics: list[SolutionMetric] = Field(default_factory=list, max_length=10)
    items: tuple[SolutionComparisonItem, SolutionComparisonItem, SolutionComparisonItem]


class SolutionToBeSide(BaseModel):
    label: Literal["TO-BE"]
    metrics: list[SolutionMetric] = Field(default_factory=list, max_length=10)
    items: tuple[SolutionToBeItem, SolutionToBeItem, SolutionToBeItem]


class SolutionComparison(BaseModel):
    as_is: SolutionComparisonSide
    to_be: SolutionToBeSide


class SolutionResponse(BaseModel):
    summary: str = Field(min_length=1, max_length=1500)
    validation: SolutionValidation
    pipeline: tuple[
        SolutionPipelineStep,
        SolutionPipelineStep,
        SolutionPipelineStep,
        SolutionPipelineStep,
    ]
    comparison: SolutionComparison


class ElaborationResponse(BaseModel):
    """POST /idea-generations/{generation_id}/elaboration 응답 바디"""

    elaboration_id: UUID
    generation_id: UUID
    selected_idea_id: UUID
    schema_version: Literal["2.0"] = "2.0"
    title: str
    summary: str
    persona: TargetPersona
    pain_point_cycle: tuple[
        PainPointCycleStepResponse,
        PainPointCycleStepResponse,
        PainPointCycleStepResponse,
    ]
    ai_coaching: AICoaching
    solution: SolutionResponse
    created_at: datetime

    @model_validator(mode="after")
    def validate_solution_relationships(self) -> "ElaborationResponse":
        pain_point_ids = {step.pain_point_id for step in self.pain_point_cycle}
        if len(pain_point_ids) != 3 or [
            step.order for step in self.pain_point_cycle
        ] != [1, 2, 3]:
            raise ValueError("페인포인트 ID는 유일하고 순서는 1, 2, 3이어야 합니다.")

        pipeline = self.solution.pipeline
        solution_step_ids = {step.solution_step_id for step in pipeline}
        if len(solution_step_ids) != 4 or [step.order for step in pipeline] != [
            1,
            2,
            3,
            4,
        ]:
            raise ValueError("해결 파이프라인 ID는 유일하고 순서는 1~4여야 합니다.")

        covered_pain_points: set[UUID] = set()
        for step in pipeline:
            if not set(step.addresses_pain_point_ids) <= pain_point_ids:
                raise ValueError("해결 단계가 존재하지 않는 페인포인트를 참조합니다.")
            covered_pain_points.update(step.addresses_pain_point_ids)
        if covered_pain_points != pain_point_ids:
            raise ValueError(
                "모든 페인포인트는 하나 이상의 해결 단계와 연결되어야 합니다."
            )

        as_is_items = self.solution.comparison.as_is.items
        to_be_items = self.solution.comparison.to_be.items
        if any(not set(item.pain_point_ids) <= pain_point_ids for item in as_is_items):
            raise ValueError("AS-IS 항목이 존재하지 않는 페인포인트를 참조합니다.")
        covered_to_be_pain_points: set[UUID] = set()
        for item in to_be_items:
            if (
                not set(item.pain_point_ids) <= pain_point_ids
                or not set(item.solution_step_ids) <= solution_step_ids
            ):
                raise ValueError(
                    "TO-BE 항목이 존재하지 않는 문제 또는 해결 단계를 참조합니다."
                )
            covered_to_be_pain_points.update(item.pain_point_ids)
        if covered_to_be_pain_points != pain_point_ids:
            raise ValueError("모든 페인포인트는 TO-BE 개선 결과와 연결되어야 합니다.")
        return self
