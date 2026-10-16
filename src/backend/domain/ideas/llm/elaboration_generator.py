import json
import logging
from typing import Protocol

import httpx
from google import genai
from google.genai import errors, types
from google.genai._gaos.errors import GenAiError
from google.genai._gaos.lib.compat_errors import APIError as InteractionsAPIError
from pydantic import BaseModel, Field, ValidationError, model_validator

from backend.core.config import settings
from backend.core.request_context import get_request_id
from backend.domain.ideas.llm.idea_generator import (
    IdeaGenerationTimeout,
    IdeaGeneratorConfigurationError,
    IdeaGeneratorRateLimited,
    IdeaGeneratorUnavailable,
    InvalidIdeaGeneration,
    SourceDocument,
)
from backend.domain.ideas.llm.response_schema import build_response_schema
from backend.domain.ideas.schemas.idea_elaboration import (
    SolutionMetric,
    SolutionValidation,
)

logger = logging.getLogger(__name__)

GeminiAPIError = errors.APIError | GenAiError | InteractionsAPIError


def normalize_evidence_point(text: str) -> str:
    """페르소나 근거 포인트 문자열을 20~25자 범위로 보정합니다."""
    cleaned = " ".join(text.strip().split())
    if len(cleaned) > 25:
        cleaned = cleaned[:24].rstrip() + " 등"
        if len(cleaned) > 25:
            cleaned = cleaned[:25]
    if len(cleaned) < 20:
        fillers = [
            " 문제 지속 발생",
            " 고질적 불편 심화",
            " 해결 방안 미흡",
            " 구조적 한계 노출",
        ]
        for filler in fillers:
            candidate = cleaned + filler
            if 20 <= len(candidate) <= 25:
                cleaned = candidate
                break
        else:
            needed = 20 - len(cleaned)
            cleaned = cleaned + (" 고질적 문제 발생"[:needed])
    return cleaned


class GeneratedPersona(BaseModel):
    title: str = Field(min_length=1, max_length=100, description="페르소나 명칭")
    description: str = Field(
        min_length=1, max_length=500, description="페르소나 상세 설명"
    )
    evidence_points: list[str] = Field(
        min_length=3,
        max_length=3,
        description="페인포인트 근거 3가지 (각 항목 공백 포함 20~25자)",
    )


class GeneratedPainPointCycleStep(BaseModel):
    step: str = Field(description="단계 표기 (단계 ①, 단계 ②, 단계 ③)")
    step_name: str = Field(min_length=1, max_length=20, description="단계명")
    title: str = Field(min_length=1, max_length=50, description="핵심 타이틀")
    description: str = Field(
        min_length=1, max_length=200, description="세부 디스크립션"
    )
    highlight_tag: str = Field(
        min_length=1, max_length=50, description="결과/수치 라벨"
    )


class GeneratedAICoaching(BaseModel):
    solution_evidence: str = Field(
        min_length=100,
        description="종합 도출 솔루션 상세 근거 문장 (300자 이상)",
    )
    feedback_review: str = Field(
        min_length=50,
        description="TIPS/창업지원 심사위원 코칭 피드백 문장 (150자 이상)",
    )


class GeneratedSolutionPipelineStep(BaseModel):
    order: int = Field(ge=1, le=4)
    category: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=100)
    subtitle: str = Field(min_length=1, max_length=150)
    description: str = Field(min_length=1, max_length=1000)
    technology_label: str = Field(min_length=1, max_length=80)
    addresses_pain_point_orders: list[int] = Field(min_length=1, max_length=3)
    metrics: list[SolutionMetric] = Field(default_factory=list, max_length=10)


class GeneratedAsIsItem(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    pain_point_orders: list[int] = Field(min_length=1, max_length=3)


class GeneratedToBeItem(GeneratedAsIsItem):
    solution_step_orders: list[int] = Field(min_length=1, max_length=4)


class GeneratedAsIsComparison(BaseModel):
    label: str = "AS-IS"
    metrics: list[SolutionMetric] = Field(default_factory=list, max_length=10)
    items: list[GeneratedAsIsItem] = Field(min_length=3, max_length=3)


class GeneratedToBeComparison(BaseModel):
    label: str = "TO-BE"
    metrics: list[SolutionMetric] = Field(default_factory=list, max_length=10)
    items: list[GeneratedToBeItem] = Field(min_length=3, max_length=3)


class GeneratedSolutionComparison(BaseModel):
    as_is: GeneratedAsIsComparison
    to_be: GeneratedToBeComparison


class GeneratedSolution(BaseModel):
    summary: str = Field(min_length=1, max_length=1500)
    validation: SolutionValidation
    pipeline: list[GeneratedSolutionPipelineStep] = Field(min_length=4, max_length=4)
    comparison: GeneratedSolutionComparison


class ProblemContextPainPoint(BaseModel):
    order: int = Field(ge=1, le=3)
    step_name: str
    title: str
    description: str
    highlight_tag: str


class ElaborationProblemContext(BaseModel):
    summary: str
    persona_title: str
    persona_description: str
    persona_evidence_points: list[str]
    pain_points: list[ProblemContextPainPoint] = Field(min_length=3, max_length=3)


class GeneratedElaboration(BaseModel):
    title: str = Field(
        min_length=1,
        max_length=200,
        description="구체화된 아이디어 제목",
    )
    summary: str = Field(
        min_length=150,
        description="상세 문제인식 본문 (200자 이상의 완성도 높은 문장)",
    )
    persona: GeneratedPersona
    pain_point_cycle: list[GeneratedPainPointCycleStep] = Field(
        min_length=3,
        max_length=3,
        description="3대 페인포인트 악순환 고리",
    )
    ai_coaching: GeneratedAICoaching
    solution: GeneratedSolution

    @staticmethod
    def _validate_pain_point_orders(orders: list[int]) -> bool:
        return len(orders) == len(set(orders)) and all(
            order in {1, 2, 3} for order in orders
        )

    @model_validator(mode="after")
    def validate_solution_relationships(self) -> "GeneratedElaboration":
        pipeline = self.solution.pipeline
        if [step.order for step in pipeline] != [1, 2, 3, 4]:
            raise ValueError("해결 파이프라인 순서는 1, 2, 3, 4여야 합니다.")

        covered_orders: set[int] = set()
        for step in pipeline:
            if not self._validate_pain_point_orders(step.addresses_pain_point_orders):
                raise ValueError(
                    "해결 단계의 페인포인트 참조 순번이 유효하지 않습니다."
                )
            covered_orders.update(step.addresses_pain_point_orders)
        if covered_orders != {1, 2, 3}:
            raise ValueError("모든 페인포인트를 해결 파이프라인에서 다뤄야 합니다.")

        for item in self.solution.comparison.as_is.items:
            if not self._validate_pain_point_orders(item.pain_point_orders):
                raise ValueError(
                    "AS-IS 항목의 페인포인트 참조 순번이 유효하지 않습니다."
                )

        covered_to_be_orders: set[int] = set()
        for item in self.solution.comparison.to_be.items:
            if (
                not self._validate_pain_point_orders(item.pain_point_orders)
                or len(item.solution_step_orders) != len(set(item.solution_step_orders))
                or any(order not in {1, 2, 3, 4} for order in item.solution_step_orders)
            ):
                raise ValueError(
                    "TO-BE 항목의 문제 또는 해결 단계 참조 순번이 유효하지 않습니다."
                )
            covered_to_be_orders.update(item.pain_point_orders)
        if covered_to_be_orders != {1, 2, 3}:
            raise ValueError("모든 페인포인트를 TO-BE 개선 결과에서 다뤄야 합니다.")
        return self


class IdeaElaborationGenerator(Protocol):
    def generate(
        self,
        prompt: str,
        selected_idea_title: str,
        selected_idea_details: list[str],
        source_documents: list[SourceDocument],
        problem_context: ElaborationProblemContext | None = None,
    ) -> GeneratedElaboration: ...


class GeminiIdeaElaborationGenerator:
    def generate(
        self,
        prompt: str,
        selected_idea_title: str,
        selected_idea_details: list[str],
        source_documents: list[SourceDocument],
        problem_context: ElaborationProblemContext | None = None,
    ) -> GeneratedElaboration:
        if (
            settings.GEMINI_API_KEY is None
            or not settings.GEMINI_API_KEY.get_secret_value().strip()
        ):
            raise IdeaGeneratorUnavailable from None
        if settings.GEMINI_BASE_URL:
            base_url = httpx.URL(settings.GEMINI_BASE_URL)
            if base_url.scheme not in {"http", "https"} or not base_url.host:
                logger.warning("Invalid Gemini base URL configuration")
                raise IdeaGeneratorConfigurationError

        request_timeout_seconds = min(settings.LLM_TIMEOUT_SECONDS, 30.0)
        client = genai.Client(
            api_key=settings.GEMINI_API_KEY.get_secret_value(),
            http_options=types.HttpOptions(
                base_url=settings.GEMINI_BASE_URL or None,
                timeout=int(request_timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(
                    attempts=1,
                    http_status_codes=[408, 500, 502, 503, 504],
                ),
            ),
        )
        documents = [
            {"filename": document.filename, "content": document.extracted_text}
            for document in source_documents
        ]

        system_instruction = (
            "당신은 스타트업 초기 창업자를 위한 전문 비즈니스 기획 및 TIPS/정부지원사업 심사위원 코칭 AI입니다.\n"
            "사용자가 선택한 특정 추천 아이디어에 맞추어 [PSST 문제인식]과 그 문제를 "
            "직접 해결하는 해결방안을 함께 생성하세요.\n"
            "상세 문제인식 본문, 타깃 페르소나, 3대 페인포인트 악순환 고리, AI 코칭, "
            "4단계 해결 파이프라인 및 AS-IS/TO-BE 비교를 작성해야 합니다.\n"
            "절대로 무관한 다른 도메인의 텍스트를 복사하거나 규격화된 더미 텍스트를 "
            "사용하지 마세요.\n\n"
            "작성 세부 지침:\n"
            "1. title: 선택한 추천 아이디어의 제목을 반영하여 명확한 사업 과제명으로 작성합니다.\n"
            "2. summary: 해당 아이디어가 해결하고자 하는 시장/사회적 배경, 구조적 문제점, "
            "기술/비즈니스적 해결 목표를 200자 이상의 충실하고 완성도 높은 문장으로 "
            "서술합니다.\n"
            "3. persona:\n"
            "   - title: 이 문제를 가장 절실하게 겪고 있는 구체적인 타깃 고객 페르소나 "
            "명칭 (예: '직장과 육아를 병행하며 식단 관리에 어려움을 겪는 30대 워킹맘 "
            "이지은')\n"
            "   - description: 페르소나의 일상적 고충과 절실한 니즈 상세 설명\n"
            "   - evidence_points: 페르소나가 겪는 핵심 페인포인트 근거 3가지. ★필수: 각 "
            "항목은 반드시 공백 포함 20자 이상 25자 이하로 작성할 것★\n"
            "4. pain_point_cycle: 해당 사업 아이디어 영역에서 발생하는 3대 페인포인트의 "
            "인과적 악순환 고리를 3단계로 정의합니다.\n"
            "   - step 필드는 반드시 순서대로 '단계 ①', '단계 ②', '단계 ③'으로 지정할 것\n"
            "   - step_name: 각 단계의 핵심 2~6자 명칭 (예: 정보탐색, 비용부담, 관리부재 등)\n"
            "   - title: 각 단계의 핵심 타이틀\n"
            "   - description: 각 단계의 세부 상황 설명\n"
            "   - highlight_tag: 각 단계의 결과 또는 영향을 나타내며, 근거 없는 수치는 넣지 않습니다.\n"
            "5. ai_coaching:\n"
            "   - solution_evidence: 문제인식과 페인포인트를 해결하는 작동 원리 및 "
            "차별성을 300자 이상 설명합니다.\n"
            "     실증되지 않은 성과를 사실처럼 쓰지 말고, 목표와 검증 계획은 실적과 "
            "구분합니다.\n"
            "   - feedback_review: TIPS 및 초기창업패키지 심사 관점의 150자 이상 "
            "코칭입니다.\n"
            "     근거가 없는 성과나 심사 점수를 이미 달성한 사실처럼 표현하지 않습니다.\n"
            "6. solution:\n"
            "   - 기존 problem_context가 제공되면 그 페인포인트만을 해결 대상으로 삼고, "
            "없다면 위에서 작성한 3개 페인포인트를 기준으로 삼습니다.\n"
            "   - summary와 파이프라인 4단계를 선택 아이디어와 페인포인트에 구체적으로 "
            "연결합니다. 각 단계의 addresses_pain_point_orders는 문제 순번 1~3만 "
            "사용합니다.\n"
            "   - validation은 실증 근거가 제공되지 않으면 status='unknown', score=null,\n"
            "     label='검증 상태 미확인', evidence_ids=[]로 작성합니다.\n"
            "   - 지표는 확인된 근거가 있을 때만 작성합니다.\n"
            "     근거가 없으면 지표를 생략하거나 status='unknown', value=null로 작성합니다.\n"
            "     수치 지표에는 basis 또는 evidence_ids를 포함합니다.\n"
            "   - comparison.as_is.items와 comparison.to_be.items는 각각 3개입니다.\n"
            "     모든 참조는 문제 순번 1~3, 해결 단계 순번 1~4만 사용하고,\n"
            "     모든 TO-BE 항목에는 양쪽 참조를 모두 포함합니다.\n"
            "   - 기존 problem_context가 주어지면 AS-IS 문구도 그 문제 설명에 근거해야 합니다."
        )

        candidate_models = [settings.GEMINI_MODEL]
        for fallback in ["gemini-3.8-flash"]:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        response_text: str | None = None
        request_succeeded = False
        last_exc = None
        last_configuration_error: GeminiAPIError | None = None
        last_rate_limit_error: GeminiAPIError | None = None

        for model_name in candidate_models:
            try:
                interaction = client.interactions.create(
                    timeout=request_timeout_seconds,
                    model=model_name,
                    input=json.dumps(
                        {
                            "project_prompt": prompt,
                            "selected_idea": {
                                "title": selected_idea_title,
                                "details": selected_idea_details,
                            },
                            "problem_context": (
                                problem_context.model_dump(mode="json")
                                if problem_context is not None
                                else None
                            ),
                            "reference_documents": documents,
                        },
                        ensure_ascii=False,
                    ),
                    system_instruction=system_instruction,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": build_response_schema(GeneratedElaboration),
                    },
                    generation_config={"max_output_tokens": 6144},
                    store=False,
                )
                response_text = interaction.output_text
                request_succeeded = True
                break
            except httpx.TimeoutException as exc:
                logger.warning(
                    "Gemini elaboration request timed out request_id=%s model=%s",
                    get_request_id(),
                    model_name,
                )
                last_exc = IdeaGenerationTimeout(str(exc))
            except (errors.APIError, GenAiError, InteractionsAPIError) as exc:
                status_code = (
                    exc.code if isinstance(exc, errors.APIError) else exc.status_code
                )
                provider_message = exc.message or "No provider message"
                logger.warning(
                    "Gemini elaboration API error request_id=%s status=%s model=%s message=%s",
                    get_request_id(),
                    status_code,
                    model_name,
                    provider_message[:500],
                )
                if status_code in {401, 403}:
                    client.close()
                    raise IdeaGeneratorConfigurationError from exc
                if status_code in {400, 404}:
                    last_configuration_error = exc
                    continue
                if status_code == 429:
                    last_rate_limit_error = exc
                    continue
                # 503 등 일시적 과부하 시 다음 후보 모델로 재시도
                last_exc = IdeaGeneratorUnavailable(str(exc))
            except httpx.RequestError as exc:
                logger.warning(
                    "Gemini elaboration connection failed request_id=%s model=%s error=%s",
                    get_request_id(),
                    model_name,
                    type(exc).__name__,
                )
                last_exc = IdeaGeneratorUnavailable(str(exc))
        client.close()

        if not request_succeeded:
            if isinstance(last_exc, IdeaGenerationTimeout):
                raise last_exc
            if last_rate_limit_error is not None:
                raise IdeaGeneratorRateLimited(
                    str(last_rate_limit_error)
                ) from last_rate_limit_error
            if last_exc is not None:
                raise IdeaGeneratorUnavailable from last_exc
            if last_configuration_error is not None:
                raise IdeaGeneratorConfigurationError from last_configuration_error
            raise IdeaGeneratorUnavailable from last_exc

        try:
            if not response_text:
                raise InvalidIdeaGeneration
            result = GeneratedElaboration.model_validate_json(response_text)
        except (ValidationError, ValueError, TypeError) as exc:
            raise InvalidIdeaGeneration from exc

        # 20~25자 제약 보정 및 단계 표준화
        normalized_points = [
            normalize_evidence_point(pt) for pt in result.persona.evidence_points
        ]
        result.persona.evidence_points = normalized_points

        expected_steps = ["단계 ①", "단계 ②", "단계 ③"]
        for idx, step in enumerate(result.pain_point_cycle[:3]):
            step.step = expected_steps[idx]

        return result
