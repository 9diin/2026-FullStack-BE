import json
import logging
from typing import Protocol

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field, ValidationError

from backend.core.config import settings
from backend.domain.ideas.llm.idea_generator import (
    IdeaGenerationTimeout,
    IdeaGeneratorConfigurationError,
    IdeaGeneratorUnavailable,
    InvalidIdeaGeneration,
    SourceDocument,
)

logger = logging.getLogger(__name__)


def normalize_evidence_point(text: str) -> str:
    """페르소나 근거 포인트 문자열을 20~25자 범위로 보정합니다."""
    cleaned = " ".join(text.strip().split())
    if len(cleaned) > 25:
        cleaned = cleaned[:24].rstrip() + " 등"
        if len(cleaned) > 25:
            cleaned = cleaned[:25]
    if len(cleaned) < 20:
        fillers = [" 문제 지속 발생", " 고질적 불편 심화", " 해결 방안 미흡", " 구조적 한계 노출"]
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
    description: str = Field(min_length=1, max_length=500, description="페르소나 상세 설명")
    evidence_points: list[str] = Field(
        min_length=3,
        max_length=3,
        description="페인포인트 근거 3가지 (각 항목 공백 포함 20~25자)",
    )


class GeneratedPainPointCycleStep(BaseModel):
    step: str = Field(description="단계 표기 (단계 ①, 단계 ②, 단계 ③)")
    step_name: str = Field(min_length=1, max_length=20, description="단계명")
    title: str = Field(min_length=1, max_length=50, description="핵심 타이틀")
    description: str = Field(min_length=1, max_length=200, description="세부 디스크립션")
    highlight_tag: str = Field(min_length=1, max_length=50, description="결과/수치 라벨")


class GeneratedAICoaching(BaseModel):
    solution_evidence: str = Field(
        min_length=100,
        description="종합 도출 솔루션 상세 근거 문장 (300자 이상)",
    )
    feedback_review: str = Field(
        min_length=50,
        description="TIPS/창업지원 심사위원 코칭 피드백 문장 (150자 이상)",
    )


class GeneratedElaboration(BaseModel):
    title: str = Field(min_length=1, max_length=200, description="구체화된 아이디어 제목")
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


class IdeaElaborationGenerator(Protocol):
    def generate(
        self,
        prompt: str,
        selected_idea_title: str,
        selected_idea_details: list[str],
        source_documents: list[SourceDocument],
    ) -> GeneratedElaboration: ...


class GeminiIdeaElaborationGenerator:
    def generate(
        self,
        prompt: str,
        selected_idea_title: str,
        selected_idea_details: list[str],
        source_documents: list[SourceDocument],
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

        client = genai.Client(
            api_key=settings.GEMINI_API_KEY.get_secret_value(),
            http_options=types.HttpOptions(
                base_url=settings.GEMINI_BASE_URL or None,
                timeout=int(settings.LLM_TIMEOUT_SECONDS * 1000),
            ),
        )
        documents = [
            {"filename": document.filename, "content": document.extracted_text}
            for document in source_documents
        ]

        system_instruction = (
            "당신은 스타트업 초기 창업자를 위한 전문 비즈니스 기획 및 TIPS/정부지원사업 심사위원 코칭 AI입니다.\n"
            "사용자가 선택한 특정 추천 아이디어에 맞추어 [PSST 문제인식] 구체화 데이터를 생성하세요.\n"
            "아이디어의 특성에 맞게 고유하고 구체적인 데이터(상세 문제인식 본문, 타깃 페르소나, 3대 페인포인트 악순환 고리, AI 코칭)를 작성해야 합니다.\n"
            "절대로 무관한 다른 도메인의 텍스트를 복사하거나 규격화된 더미 텍스트를 사용하지 마세요.\n\n"
            "작성 세부 지침:\n"
            "1. title: 선택한 추천 아이디어의 제목을 반영하여 명확한 사업 과제명으로 작성합니다.\n"
            "2. summary: 해당 아이디어가 해결하고자 하는 시장/사회적 배경, 구조적 문제점, 기술/비즈니스적 해결 목표를 200자 이상의 충실하고 완성도 높은 문장으로 서술합니다.\n"
            "3. persona:\n"
            "   - title: 이 문제를 가장 절실하게 겪고 있는 구체적인 타깃 고객 페르소나 명칭 (예: '직장과 육아를 병행하며 식단 관리에 어려움을 겪는 30대 워킹맘 이지은')\n"
            "   - description: 페르소나의 일상적 고충과 절실한 니즈 상세 설명\n"
            "   - evidence_points: 페르소나가 겪는 핵심 페인포인트 근거 3가지. ★필수: 각 항목은 반드시 공백 포함 20자 이상 25자 이하로 작성할 것★\n"
            "4. pain_point_cycle: 해당 사업 아이디어 영역에서 발생하는 3대 페인포인트의 인과적 악순환 고리를 3단계로 정의합니다.\n"
            "   - step 필드는 반드시 순서대로 '단계 ①', '단계 ②', '단계 ③'으로 지정할 것\n"
            "   - step_name: 각 단계의 핵심 2~6자 명칭 (예: 정보탐색, 비용부담, 관리부재 등)\n"
            "   - title: 각 단계의 핵심 타이틀\n"
            "   - description: 각 단계의 세부 상황 설명\n"
            "   - highlight_tag: 각 단계의 결과/수치/영향 라벨 (예: '비자발적 초과 지출', '평균 탐색 15일 소요' 등)\n"
            "5. ai_coaching:\n"
            "   - solution_evidence: 문제인식, 페르소나, 3대 페인포인트를 해결하기 위한 솔루션의 작동 원리, 차별성, 검증 지표를 300자 이상의 상세한 문장으로 서술합니다.\n"
            "   - feedback_review: TIPS 및 초기창업패키지 심사위원 평가 관점의 코칭 피드백. 강점을 칭찬하고 비즈니스 모델(수익화, Unit Economics 등) 보강을 권고하는 150자 이상의 코칭 문장을 작성합니다."
        )

        candidate_models = [settings.GEMINI_MODEL]
        for fallback in ["gemini-3.5-flash", "gemini-2.5-flash-lite"]:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        response = None
        last_exc = None

        for model_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=json.dumps(
                        {
                            "project_prompt": prompt,
                            "selected_idea": {
                                "title": selected_idea_title,
                                "details": selected_idea_details,
                            },
                            "reference_documents": documents,
                        },
                        ensure_ascii=False,
                    ),
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=GeneratedElaboration,
                        max_output_tokens=2048,
                    ),
                )
                break
            except httpx.TimeoutException as exc:
                logger.warning("Gemini elaboration request timed out on %s", model_name)
                last_exc = IdeaGenerationTimeout(str(exc))
            except errors.APIError as exc:
                logger.warning("Gemini API error status=%s on %s", exc.code, model_name)
                if exc.code in {400, 401, 403, 404}:
                    client.close()
                    raise IdeaGeneratorConfigurationError from exc
                # 503 등 일시적 과부하 시 다음 후보 모델로 재시도
                last_exc = IdeaGeneratorUnavailable(str(exc))
            except httpx.RequestError as exc:
                logger.warning("Gemini connection failed on %s: %s", model_name, type(exc).__name__)
                last_exc = IdeaGeneratorUnavailable(str(exc))
        client.close()

        if response is None:
            if isinstance(last_exc, IdeaGenerationTimeout):
                raise last_exc
            raise IdeaGeneratorUnavailable from last_exc

        try:
            if response.parsed is not None:
                result = GeneratedElaboration.model_validate(response.parsed)
            elif response.text:
                result = GeneratedElaboration.model_validate_json(response.text)
            else:
                raise InvalidIdeaGeneration
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
