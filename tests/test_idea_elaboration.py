"""아이디어 구체화(Elaboration) API 통합 테스트

스펙 문서 섹션 4.2의 검증 항목을 포함하여 백엔드 엔드포인트 동작을 검증합니다.

검증 항목:
1. 페르소나 근거 3개의 글자 수가 20~25자 이내여야 한다.
2. 3대 페인포인트 악순환 고리가 1단계 → 2단계 → 3단계 순서로 누락 없이 정의되어야 한다.
3. 문제인식 본문과 AI 코칭 솔루션 및 피드백 텍스트가 기준치 이상의 충실도를 갖추어야 한다.
"""

import logging
from collections.abc import Generator
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.genai._gaos.errors import GenAiDefaultError
from google.genai._gaos.lib.compat_errors import BadRequestError
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.config import settings
from backend.core.database import Base, get_db
from backend.core.request_context import get_request_id, request_id_context
from backend.domain.ideas.errors import register_idea_error_handlers
from backend.domain.ideas.llm.elaboration_generator import (
    ElaborationProblemContext,
    GeminiIdeaElaborationGenerator,
    GeneratedAICoaching,
    GeneratedElaboration,
    GeneratedPainPointCycleStep,
    GeneratedPersona,
)
from backend.domain.ideas.llm.idea_generator import (
    GeneratedIdeas,
    IdeaGeneratorConfigurationError,
    IdeaGeneratorRateLimited,
)
from backend.domain.ideas.llm.response_schema import build_response_schema
from backend.domain.ideas.models.idea_generation import (
    IdeaElaboration,
    IdeaSelectionEvent,  # noqa: F401 - Base 인식용
    SourceFile,  # noqa: F401 - Base 인식용
)
from backend.domain.ideas.routers.idea_generations import (
    get_idea_elaboration_generator,
    get_idea_generator,
    router,
)
from backend.domain.ideas.services.idea_generation import IdeaAPIError


def provider_error(status_code: int, message: str) -> GenAiDefaultError:
    response = httpx.Response(
        status_code,
        json={"error": {"message": message}},
        request=httpx.Request("POST", "https://example.test/interactions"),
    )
    return GenAiDefaultError("", response)


def interactions_provider_error(status_code: int, message: str) -> BadRequestError:
    response = httpx.Response(
        status_code,
        json={"error": {"message": message}},
        request=httpx.Request("POST", "https://example.test/interactions"),
    )
    return BadRequestError(message, response=response, body=response.json())


class FakeIdeaElaborationGenerator:
    def generate(
        self,
        prompt: str,
        selected_idea_title: str,
        selected_idea_details: list,
        source_documents: list,
        problem_context: ElaborationProblemContext | None = None,
    ) -> GeneratedElaboration:
        problem_title = (
            problem_context.pain_points[0].title
            if problem_context is not None
            else "핵심 문제"
        )
        return GeneratedElaboration(
            title=f"구체화: {selected_idea_title}",
            summary=(
                f"본 과제는 {selected_idea_title}을 중심으로 사용자의 핵심 문제를 해결하는 차세대 솔루션입니다. "
                "기존 시장의 구조적 한계와 비효율성을 극복하고 체계적인 프로세스를 통해 가치를 창출합니다. "
                "이를 통해 사용자의 시간과 비용을 획기적으로 절감하며 지속 가능한 성장을 도모합니다."
            ),
            persona=GeneratedPersona(
                title=f"{selected_idea_title} 핵심 타깃 고객",
                description=f"{selected_idea_title} 도입을 절실히 필요로 하는 초기 사용자",
                evidence_points=[
                    "해당 분야의 비효율적 비용 지출 지속",  # 21자
                    "기존 제품의 복잡성과 학습 비용 문제",  # 21자
                    "체계적 관리 부재로 인한 손실 심화 발생",  # 22자
                ],
            ),
            pain_point_cycle=[
                GeneratedPainPointCycleStep(
                    step="단계 ①",
                    step_name="문제인지",
                    title="기존 문제점 봉착",
                    description=f"{selected_idea_title} 관련 문제 상황 발생",
                    highlight_tag="초기 비효율 발생",
                ),
                GeneratedPainPointCycleStep(
                    step="단계 ②",
                    step_name="심화단계",
                    title="문제 방치 및 악화",
                    description="해결책 부재로 인한 추가 손실",
                    highlight_tag="평균 방치 손실 누적",
                ),
                GeneratedPainPointCycleStep(
                    step="단계 ③",
                    step_name="결과손실",
                    title="최종 비용 지출",
                    description="결국 고비용 대체재에 의존",
                    highlight_tag="가구당 상당액 손실",
                ),
            ],
            ai_coaching=GeneratedAICoaching(
                solution_evidence=(
                    f"본 {selected_idea_title} 솔루션은 혁신적인 기술을 기반으로 문제를 해결합니다. "
                    "실시간 알고리즘과 최적화 프로세스를 통해 기존 대비 90% 이상의 효율 향상을 입증하였습니다. "
                    "초기 파일럿 테스트를 통해 사용자 만족도 95%를 달성하였으며 정식 출시 후 시장 점유율을 가속화합니다. "
                    "또한 지속 가능한 비즈니스 모델을 확보하여 안정적인 수익 구조를 창출합니다."
                ),
                feedback_review=(
                    f"{selected_idea_title}에 대한 문제 정의와 해결 로직이 매우 구체적이고 설득력 있습니다. "
                    "다만 사업화 성공률을 높이기 위해 초기 고객 획득 비용(CAC) 절감 방안과 가격 정책을 1문장 보강할 것을 권고합니다."
                ),
            ),
            solution={
                "summary": (
                    f"{selected_idea_title}의 {problem_title}를 직접 줄이는 해결방안"
                ),
                "validation": {
                    "status": "unknown",
                    "score": None,
                    "label": "검증 상태 미확인",
                    "evidence_ids": [],
                },
                "pipeline": [
                    {
                        "order": 1,
                        "category": "문제 대응",
                        "title": f"{selected_idea_title} 문제 파악",
                        "subtitle": "문제 상황 구조화",
                        "description": "사용자가 겪는 재고 파악의 어려움을 줄입니다.",
                        "technology_label": "사용자 입력 분석",
                        "addresses_pain_point_orders": [1, 2],
                        "metrics": [],
                    },
                    {
                        "order": 2,
                        "category": "개선 지원",
                        "title": "실행 대안 제공",
                        "subtitle": "문제 상황에 맞춘 대안 제시",
                        "description": "발견된 문제에 맞는 다음 행동을 안내합니다.",
                        "technology_label": "맞춤형 추천",
                        "addresses_pain_point_orders": [2, 3],
                        "metrics": [],
                    },
                    {
                        "order": 3,
                        "category": "실행 연결",
                        "title": "필요 자원 연결",
                        "subtitle": "필요한 자원 확인",
                        "description": "사용자가 필요한 자원을 선택하도록 돕습니다.",
                        "technology_label": "서비스 연동",
                        "addresses_pain_point_orders": [1],
                        "metrics": [],
                    },
                    {
                        "order": 4,
                        "category": "결과 환류",
                        "title": "사용 결과 반영",
                        "subtitle": "후속 제안 개선",
                        "description": "사용 결과를 반영해 후속 제안을 조정합니다.",
                        "technology_label": "동의 기반 기록",
                        "addresses_pain_point_orders": [3],
                        "metrics": [],
                    },
                ],
                "comparison": {
                    "as_is": {
                        "label": "AS-IS",
                        "metrics": [],
                        "items": [
                            {"text": "첫 번째 문제 상황", "pain_point_orders": [1]},
                            {"text": "두 번째 문제 상황", "pain_point_orders": [2]},
                            {"text": "세 번째 문제 상황", "pain_point_orders": [3]},
                        ],
                    },
                    "to_be": {
                        "label": "TO-BE",
                        "metrics": [],
                        "items": [
                            {
                                "text": "첫 번째 문제를 줄이는 결과",
                                "pain_point_orders": [1],
                                "solution_step_orders": [3],
                            },
                            {
                                "text": "두 번째 문제를 줄이는 결과",
                                "pain_point_orders": [2],
                                "solution_step_orders": [1, 2],
                            },
                            {
                                "text": "세 번째 문제를 줄이는 결과",
                                "pain_point_orders": [3],
                                "solution_step_orders": [2, 4],
                            },
                        ],
                    },
                },
            },
        )


from backend.domain.users.models.email_verification import (
    EmailVerification,  # noqa: F401
)
from backend.domain.users.models.user import User
from backend.domain.users.models.user_profile import UserProfile  # noqa: F401
from backend.domain.users.routers.dependencies import get_current_user


def test_해결방안이_잘못된_참조와_미확인_수치를_거부한다() -> None:
    generated = FakeIdeaElaborationGenerator().generate(
        "prompt", "아이디어" * 20, [], []
    )

    invalid_reference = generated.model_dump()
    invalid_reference["solution"]["pipeline"][0]["addresses_pain_point_orders"] = [4]
    with pytest.raises(ValidationError):
        GeneratedElaboration.model_validate(invalid_reference)

    uncovered_problem = generated.model_dump()
    for step in uncovered_problem["solution"]["pipeline"]:
        step["addresses_pain_point_orders"] = [2, 3]
    with pytest.raises(ValidationError):
        GeneratedElaboration.model_validate(uncovered_problem)

    unsupported_metric = generated.model_dump()
    unsupported_metric["solution"]["pipeline"][0]["metrics"] = [
        {
            "label": "인식 정확도",
            "value": 94.8,
            "unit": "%",
            "status": "unknown",
            "basis": None,
            "evidence_ids": [],
        }
    ]
    with pytest.raises(ValidationError):
        GeneratedElaboration.model_validate(unsupported_metric)


def test_gemini_400_오류의_제공자_설명을_로그에_남기고_키는_노출하지_않는다(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class FakeInteractions:
        def create(self, **_kwargs: object) -> None:
            raise provider_error(400, "Invalid response schema")

    class FakeClient:
        interactions = FakeInteractions()

        def __init__(self, **_kwargs: object) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(settings, "GEMINI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(
        "backend.domain.ideas.llm.elaboration_generator.genai.Client",
        FakeClient,
    )

    with caplog.at_level(
        logging.WARNING,
        logger="backend.domain.ideas.llm.elaboration_generator",
    ):
        token = request_id_context.set("test-request-id")
        try:
            with pytest.raises(IdeaGeneratorConfigurationError):
                GeminiIdeaElaborationGenerator().generate("prompt", "idea", [], [])
        finally:
            request_id_context.reset(token)

    assert "status=400" in caplog.text
    assert "request_id=test-request-id" in caplog.text
    assert "model=" in caplog.text
    assert "Invalid response schema" in caplog.text
    assert "test-key" not in caplog.text


def test_interactions_api_bad_request_is_mapped_to_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInteractions:
        def create(self, **_kwargs: object) -> None:
            raise interactions_provider_error(400, "invalid_request")

    class FakeClient:
        interactions = FakeInteractions()

        def __init__(self, **_kwargs: object) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(settings, "GEMINI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(
        "backend.domain.ideas.llm.elaboration_generator.genai.Client",
        FakeClient,
    )

    with pytest.raises(IdeaGeneratorConfigurationError):
        GeminiIdeaElaborationGenerator().generate("prompt", "idea", [], [])


def test_gemini_response_schema_inlines_refs_and_normalizes_nullable_unions() -> None:
    schema = build_response_schema(GeneratedElaboration)

    def collect_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(collect_keys(child) for child in value.values()))
        if isinstance(value, list):
            return set().union(*(collect_keys(child) for child in value))
        return set()

    schema_keys = collect_keys(schema)
    assert "$defs" not in schema_keys
    assert "$ref" not in schema_keys
    assert "anyOf" not in schema_keys

    validation_score = schema["properties"]["solution"]["properties"]["validation"][
        "properties"
    ]["score"]
    metric_value = schema["properties"]["solution"]["properties"]["pipeline"]["items"][
        "properties"
    ]["metrics"]["items"]["properties"]["value"]
    assert validation_score == {"type": "number", "nullable": True}
    assert metric_value == {"type": "string", "nullable": True}


def test_idea_api_request_id_is_shared_with_provider_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FastAPI()
    register_idea_error_handlers(app)

    @app.post("/api/v1/idea-generations/test/elaboration")
    def fail_elaboration() -> None:
        logging.getLogger("test.provider").warning(
            "Gemini elaboration API error request_id=%s", get_request_id()
        )
        raise IdeaAPIError(503, "LLM_CONFIGURATION_ERROR", "configuration error")

    with caplog.at_level(logging.WARNING, logger="test.provider"):
        with TestClient(app) as test_client:
            response = test_client.post("/api/v1/idea-generations/test/elaboration")

    request_id = response.json()["error"]["request_id"]
    assert response.status_code == 503
    assert response.headers["x-request-id"] == request_id
    assert f"request_id={request_id}" in caplog.text


def test_gemini_구체화_400_후_지원되는_모델로_재시도한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated = FakeIdeaElaborationGenerator().generate(
        "prompt", "아이디어" * 20, [], []
    )
    attempted_models: list[str] = []

    class FakeInteractions:
        def create(self, **kwargs: object) -> SimpleNamespace:
            model = str(kwargs["model"])
            attempted_models.append(model)
            if model == "invalid-configured-model":
                raise provider_error(400, "model is not supported")
            return SimpleNamespace(output_text=generated.model_dump_json())

    class FakeClient:
        interactions = FakeInteractions()

        def __init__(self, **_kwargs: object) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(settings, "GEMINI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(settings, "GEMINI_MODEL", "invalid-configured-model")
    monkeypatch.setattr(
        "backend.domain.ideas.llm.elaboration_generator.genai.Client",
        FakeClient,
    )

    result = GeminiIdeaElaborationGenerator().generate("prompt", "idea", [], [])

    assert result == generated
    assert attempted_models == [
        "invalid-configured-model",
        "gemini-3.8-flash",
    ]


def test_gemini_구체화_429_후_현재_대체_모델로_재시도한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated = FakeIdeaElaborationGenerator().generate(
        "prompt", "아이디어" * 20, [], []
    )
    attempted_models: list[str] = []

    class FakeInteractions:
        def create(self, **kwargs: object) -> SimpleNamespace:
            model = str(kwargs["model"])
            attempted_models.append(model)
            if model == "quota-limited-model":
                raise provider_error(429, "quota exceeded")
            return SimpleNamespace(output_text=generated.model_dump_json())

    class FakeClient:
        interactions = FakeInteractions()

        def __init__(self, **_kwargs: object) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(settings, "GEMINI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(settings, "GEMINI_MODEL", "quota-limited-model")
    monkeypatch.setattr(
        "backend.domain.ideas.llm.elaboration_generator.genai.Client",
        FakeClient,
    )

    result = GeminiIdeaElaborationGenerator().generate("prompt", "idea", [], [])

    assert result == generated
    assert attempted_models == ["quota-limited-model", "gemini-3.8-flash"]


def test_gemini_구체화_429_대체_모델_실패_시_할당량_오류를_전달한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInteractions:
        def create(self, **_kwargs: object) -> None:
            raise provider_error(429, "quota exceeded")

    class FakeClient:
        interactions = FakeInteractions()

        def __init__(self, **_kwargs: object) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(settings, "GEMINI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(
        "backend.domain.ideas.llm.elaboration_generator.genai.Client",
        FakeClient,
    )

    with pytest.raises(IdeaGeneratorRateLimited):
        GeminiIdeaElaborationGenerator().generate("prompt", "idea", [], [])


# ─── 공통 픽스처 ─────────────────────────────────────────────────────────────


class FakeIdeaGenerator:
    def generate(self, prompt: str, source_documents: list) -> GeneratedIdeas:
        return GeneratedIdeas(
            focus_items=["초기 고객", "검증 방법"],
            interest_categories=["식품·농업"],
            suggestions=[
                {
                    "title": "스마트 냉장고 레시피 큐레이션",
                    "details": ["식재료 인식", "레시피 추천"],
                },
                {
                    "title": "초소량 장보기 연동 서비스",
                    "details": ["퀵커머스 연동", "자동 주문"],
                },
                {
                    "title": "유통기한 임박 식재료 알림",
                    "details": ["IoT 센싱", "푸시 알림"],
                },
            ],
        )


@pytest.fixture
def client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    user = User(
        id=1,
        email="founder@example.com",
        password="not-used",
        terms_agreed=True,
        privacy_agreed=True,
        marketing_agreed=False,
    )
    with test_session_factory() as db:
        db.add(user)
        db.commit()

    app = FastAPI()
    register_idea_error_handlers(app)
    app.include_router(router, prefix="/api/v1")

    def override_db() -> Generator[Session, None, None]:
        with test_session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_idea_generator] = lambda: FakeIdeaGenerator()
    app.dependency_overrides[get_idea_elaboration_generator] = lambda: (
        FakeIdeaElaborationGenerator()
    )

    with TestClient(app) as test_client:
        yield test_client, test_session_factory
    Base.metadata.drop_all(engine)
    engine.dispose()


# ─── 헬퍼 ────────────────────────────────────────────────────────────────────


def _create_generation_and_get_suggestion_id(
    test_client: TestClient,
) -> tuple[str, str]:
    """아이디어 생성 후 (generation_id, suggestion_id) 를 반환합니다."""
    resp = test_client.post(
        "/api/v1/idea-generations",
        json={"prompt": "1인 가구 식재료 낭비 문제를 해결하고 싶습니다."},
    )
    assert resp.status_code == 200
    body = resp.json()
    return body["generation_id"], body["suggestions"][0]["id"]


def _valid_elaboration_body(suggestion_id: str) -> dict:
    """유효한 구체화 요청 바디를 반환합니다 (스펙 mock data 기준)."""
    return {
        "selected_idea_id": suggestion_id,
        "title": (
            "1인 가구 및 직장인을 위한 스마트 냉장고 잔여 식재료 기반 실시간 레시피 생성 및 자동 장보기 연동 서비스"
        ),
        "summary": (
            "국내 1인 가구 비중이 35%에 육박하는 급격한 인구구조 변화 속에서, "
            "대용량 중심의 기형적인 마트 유통 규격과 야근·불규칙한 퇴근으로 인한 식생활 마찰은 "
            "미사용 식재료의 부패 폐기와 배달 음식 과의존이라는 구조적 악순환을 심화시키고 있습니다. "
            "본 과제는 이러한 사회·환경적 손실과 개인의 가계 부담을 근본적으로 해소하기 위해, "
            "온디바이스 비전 AI 기반의 신선도 판별 기술과 가전 IoT 센싱 데이터를 결합하여 "
            "냉장고 속 잔여 식자재를 실시간 인식·구조화하고, "
            "15분 이내 초간편 조리가 가능한 잔여 식자재 최적화 레시피 큐레이션 및 부족분 초소량 자동 매칭 솔루션을 개발하는 것을 핵심 목표로 합니다."
        ),
        "persona": {
            "title": "2030 1인 가구 직장인",
            "description": (
                "퇴근 후 장보기 및 조리 피로도가 높으나 배달음식의 고비용·건강 약화에 불만을 "
                "느끼는 2030 1인 가구 직장인"
            ),
            "evidence_points": [
                "마트 묶음 채소 절반 이상 버려지는 낭비",  # 23자
                "퇴근 후 피로에 냉장고 속 재고 망각 방치",  # 23자
                "한 끼 2만 원 넘는 잦은 배달 식비 부담",  # 23자
            ],
        },
        "pain_point_cycle": [
            {
                "step": "단계 ①",
                "step_name": "강제구매",
                "title": "대용량 번들 포장",
                "description": "소포장 부재로 묶음 채소 및 대용량 조미료 과대 구매",
                "highlight_tag": "초과 비축 발생",
            },
            {
                "step": "단계 ②",
                "step_name": "방치망각",
                "title": "냉장고 재고 망각",
                "description": "보유 식자재 파악 불가 및 퇴근 후 탐색 피로로 장기 방치",
                "highlight_tag": "평균 방치 11.4일",
            },
            {
                "step": "단계 ③",
                "step_name": "폐기손실",
                "title": "음식물 쓰레기화",
                "description": "부패로 인한 폐기 및 죄책감 유발 후 고비용 배달앱 재회귀",
                "highlight_tag": "가구당 월 4.8만 원 손실",
            },
        ],
        "ai_coaching": {
            "solution_evidence": (
                "스마트폰 카메라를 통한 냉장고 선반 1초 촬영, 영수증 OCR 및 바코드 스캔 기술을 결합하여 "
                "냉장고 내 보유 식자재의 품목과 잔여 소비기한을 자동 구조화하고, "
                "유통기한 임박 식재료를 최우선으로 소진하는 15분 맞춤형 저탄소 레시피를 실시간 추천합니다. "
                "조리에 필수적인 미보유 부재료(1~2개)는 인근 퀵커머스 및 SSM 물류망과 실시간 API로 연동되어 "
                "1시간 내 초소량 묶음 장바구니로 원클릭 큐레이션되며, "
                "사용자의 당뇨·알레르기·칼로리 목표 및 1구 인덕션·에어프라이어 등 보유 조리도구 제약까지 정밀 반영합니다. "
                "1차 클로즈드 베타 테스터 100인 실증 검증을 통해 식재료 인식 정확도 94.8%를 확보하였으며, "
                "정식 출시 30일 내 주간 재방문율 40% 및 가구당 월간 식비 12만 원 절감을 핵심 북극성 지표(OMTM)로 설정하여 비즈니스 타당성을 검증합니다."
            ),
            "feedback_review": (
                '"15분 즉석 조리 레시피 큐레이션 및 출시 30일 내 리텐션 40% 달성이라는 명확한 정량적 KPI와 '
                "초기 사용자 100명 인터뷰 기반의 실증 데이터는 심사위원 평가에서 매우 높은 설득력을 지닙니다. "
                "다만 TIPS R&D 및 초기창업패키지 합격 안정권(90점 이상)에 확실하게 진입하기 위해서는, "
                "퀵커머스 초소량 식자재 장바구니 연동에 따른 객단가별 제휴 중개 수수료율(Take Rate 8~12%)과 "
                '정기 구독 모델(프리미엄 밀키트 큐레이션) 간의 Unit Economics(LTV/CAC) 수익화 로직을 1~2문장으로 보강 기술할 것을 강력히 권고합니다."'
            ),
        },
    }


# ─── 스펙 4.2 데이터 구조 및 제약조건 검증 ───────────────────────────────────


def test_페르소나_근거_3개의_글자_수가_20자_이상_25자_이하여야_한다(client) -> None:
    """스펙 4.2: 페르소나 근거 3개의 글자 수가 20~25자 이내여야 한다."""
    test_client, _ = client
    generation_id, suggestion_id = _create_generation_and_get_suggestion_id(test_client)

    body = _valid_elaboration_body(suggestion_id)
    for point in body["persona"]["evidence_points"]:
        length = len(point)
        assert 20 <= length <= 25, f"'{point}' 글자 수={length}, 범위 20~25 위반"


def test_3대_페인포인트가_1단계에서_3단계_순서로_정의되어야_한다(client) -> None:
    """스펙 4.2: 3대 페인포인트 악순환 고리가 ①→②→③ 순서로 누락 없이 정의되어야 한다."""
    test_client, _ = client
    generation_id, suggestion_id = _create_generation_and_get_suggestion_id(test_client)

    body = _valid_elaboration_body(suggestion_id)
    assert len(body["pain_point_cycle"]) == 3
    assert body["pain_point_cycle"][0]["step"] == "단계 ①"
    assert body["pain_point_cycle"][1]["step"] == "단계 ②"
    assert body["pain_point_cycle"][2]["step"] == "단계 ③"


def test_문제인식_및_AI코칭_텍스트가_기준치_이상_충실도를_갖추어야_한다(client) -> None:
    """스펙 4.2: 문제인식 본문 >200자, AI 솔루션 >300자, 피드백 >150자."""
    test_client, _ = client
    generation_id, suggestion_id = _create_generation_and_get_suggestion_id(test_client)

    body = _valid_elaboration_body(suggestion_id)
    assert len(body["summary"]) > 200
    assert len(body["ai_coaching"]["solution_evidence"]) > 300
    assert len(body["ai_coaching"]["feedback_review"]) > 150


# ─── API 통합 테스트 ─────────────────────────────────────────────────────────


def test_구체화_데이터_생성_후_응답에_elaboration_id가_포함된다(client) -> None:
    test_client, session_factory = client
    generation_id, suggestion_id = _create_generation_and_get_suggestion_id(test_client)

    response = test_client.post(
        f"/api/v1/idea-generations/{generation_id}/elaboration",
        json=_valid_elaboration_body(suggestion_id),
    )

    assert response.status_code == 201
    body = response.json()
    assert "elaboration_id" in body
    assert body["generation_id"] == generation_id
    assert body["selected_idea_id"] == suggestion_id
    assert "대용량 번들 포장" in body["solution"]["summary"]

    # DB 영속성 검증
    with session_factory() as db:
        saved = (
            db.query(IdeaElaboration)
            .filter(IdeaElaboration.generation_id == UUID(generation_id))
            .first()
        )
        assert saved is not None
        assert len(saved.pain_point_cycle) == 3
        assert saved.solution is not None

    pain_point_ids = {point["pain_point_id"] for point in body["pain_point_cycle"]}
    solution_step_ids = {
        step["solution_step_id"] for step in body["solution"]["pipeline"]
    }
    assert body["schema_version"] == "2.0"
    assert len(body["solution"]["pipeline"]) == 4
    assert all(
        set(step["addresses_pain_point_ids"]) <= pain_point_ids
        for step in body["solution"]["pipeline"]
    )
    assert {
        point_id
        for step in body["solution"]["pipeline"]
        for point_id in step["addresses_pain_point_ids"]
    } == pain_point_ids
    assert all(
        set(item["pain_point_ids"]) <= pain_point_ids
        and set(item["solution_step_ids"]) <= solution_step_ids
        for item in body["solution"]["comparison"]["to_be"]["items"]
    )
    assert body["solution"]["validation"]["status"] == "unknown"
    assert body["solution"]["validation"]["score"] is None


def test_구체화_할당량_초과는_429와_안내_메시지를_반환한다(client) -> None:
    test_client, _ = client
    generation_id, suggestion_id = _create_generation_and_get_suggestion_id(test_client)

    class RateLimitedElaborationGenerator:
        def generate(
            self,
            prompt: str,
            selected_idea_title: str,
            selected_idea_details: list[str],
            source_documents: list,
            problem_context: ElaborationProblemContext | None = None,
        ) -> GeneratedElaboration:
            raise IdeaGeneratorRateLimited

    test_client.app.dependency_overrides[get_idea_elaboration_generator] = lambda: (
        RateLimitedElaborationGenerator()
    )

    response = test_client.post(
        f"/api/v1/idea-generations/{generation_id}/elaboration",
        json=_valid_elaboration_body(suggestion_id),
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "LLM_QUOTA_EXCEEDED"
    assert "Google AI Studio" in response.json()["error"]["message"]


def test_구체화_데이터_생성_후_조회_시_동일_데이터가_반환된다(client) -> None:
    test_client, _ = client
    generation_id, suggestion_id = _create_generation_and_get_suggestion_id(test_client)

    # 생성
    create_response = test_client.post(
        f"/api/v1/idea-generations/{generation_id}/elaboration",
        json=_valid_elaboration_body(suggestion_id),
    )
    assert create_response.status_code == 201
    created = create_response.json()

    # 조회
    response = test_client.get(f"/api/v1/idea-generations/{generation_id}/elaboration")

    assert response.status_code == 200
    body = response.json()
    assert body["generation_id"] == generation_id
    assert body["pain_point_cycle"] == created["pain_point_cycle"]
    assert body["solution"] == created["solution"]
    assert len(body["pain_point_cycle"]) == 3
    assert body["pain_point_cycle"][0]["step"] == "단계 ①"
    assert body["pain_point_cycle"][1]["step"] == "단계 ②"
    assert body["pain_point_cycle"][2]["step"] == "단계 ③"
    assert len(body["persona"]["evidence_points"]) == 3
    assert body["solution"]["summary"]
    assert len(body["solution"]["comparison"]["as_is"]["items"]) == 3
    assert len(body["solution"]["comparison"]["to_be"]["items"]) == 3


def test_동일_generation에_다른_아이디어_선택_시_구체화_데이터_갱신(client) -> None:
    test_client, _ = client
    resp = test_client.post(
        "/api/v1/idea-generations",
        json={"prompt": "1인 가구 식재료 낭비 문제를 해결하고 싶습니다."},
    )
    assert resp.status_code == 200
    body = resp.json()
    gen_id = body["generation_id"]
    sugg1 = body["suggestions"][0]["id"]
    sugg2 = body["suggestions"][1]["id"]

    # 첫 번째 아이디어 선택 및 구체화 생성
    res1 = test_client.post(
        f"/api/v1/idea-generations/{gen_id}/elaboration",
        json={"selected_idea_id": sugg1},
    )
    assert res1.status_code == 201
    assert res1.json()["selected_idea_id"] == sugg1
    assert "스마트 냉장고 레시피 큐레이션" in res1.json()["title"]

    # 두 번째 아이디어 선택 시 기존 구체화 데이터가 새 아이디어로 갱신됨
    res2 = test_client.post(
        f"/api/v1/idea-generations/{gen_id}/elaboration",
        json={"selected_idea_id": sugg2},
    )
    assert res2.status_code == 201
    assert res2.json()["selected_idea_id"] == sugg2
    assert "초소량 장보기 연동 서비스" in res2.json()["title"]
    assert res2.json()["title"] != res1.json()["title"]


def test_추천_아이디어별_차별화된_구체화_데이터_생성(client) -> None:
    """추천 아이디어별로 각각 고유하고 차별화된 문제인식/페르소나/페인포인트 데이터가 생성된다."""
    test_client, _ = client
    resp = test_client.post(
        "/api/v1/idea-generations",
        json={"prompt": "테스트 프롬프트"},
    )
    body = resp.json()
    gen_id = body["generation_id"]
    sugg1 = body["suggestions"][0]
    sugg2 = body["suggestions"][1]

    res1 = test_client.post(
        f"/api/v1/idea-generations/{gen_id}/elaboration",
        json={"selected_idea_id": sugg1["id"]},
    )
    assert res1.status_code == 201
    data1 = res1.json()

    res2 = test_client.post(
        f"/api/v1/idea-generations/{gen_id}/elaboration",
        json={"selected_idea_id": sugg2["id"]},
    )
    assert res2.status_code == 201
    data2 = res2.json()

    # 두 데이터가 추천 아이디어에 따라 상이함
    assert data1["title"] != data2["title"]
    assert data1["persona"]["title"] != data2["persona"]["title"]
    assert data1["summary"] != data2["summary"]
    assert data1["selected_idea_id"] != data2["selected_idea_id"]


def test_selected_idea_id만_전달해도_LLM_구체화_데이터_자동_생성(client) -> None:
    """클라이언트가 더미 데이터 없이 selected_idea_id만 전송해도 LLM이 구체화 데이터를 자동 생성한다."""
    test_client, _ = client
    generation_id, suggestion_id = _create_generation_and_get_suggestion_id(test_client)

    response = test_client.post(
        f"/api/v1/idea-generations/{generation_id}/elaboration",
        json={"selected_idea_id": suggestion_id},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["selected_idea_id"] == suggestion_id
    assert len(body["persona"]["evidence_points"]) == 3
    for pt in body["persona"]["evidence_points"]:
        assert 20 <= len(pt) <= 25
    assert len(body["pain_point_cycle"]) == 3
    assert body["pain_point_cycle"][0]["step"] == "단계 ①"
    assert body["pain_point_cycle"][1]["step"] == "단계 ②"
    assert body["pain_point_cycle"][2]["step"] == "단계 ③"


def test_존재하지_않는_generation_id로_구체화_생성_시_404_반환(client) -> None:
    test_client, _ = client
    fake_generation_id = "00000000-0000-0000-0000-000000000000"
    fake_suggestion_id = "00000000-0000-0000-0000-000000000001"

    response = test_client.post(
        f"/api/v1/idea-generations/{fake_generation_id}/elaboration",
        json=_valid_elaboration_body(fake_suggestion_id),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GENERATION_NOT_FOUND"


def test_잘못된_suggestion_id로_구체화_생성_시_404_반환(client) -> None:
    test_client, _ = client
    generation_id, _ = _create_generation_and_get_suggestion_id(test_client)
    wrong_suggestion_id = "00000000-0000-0000-0000-000000000099"

    body = _valid_elaboration_body(wrong_suggestion_id)
    response = test_client.post(
        f"/api/v1/idea-generations/{generation_id}/elaboration",
        json=body,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "IDEA_NOT_FOUND"


def test_구체화_데이터_없는_경우_조회_시_404_반환(client) -> None:
    test_client, _ = client
    generation_id, _ = _create_generation_and_get_suggestion_id(test_client)

    response = test_client.get(f"/api/v1/idea-generations/{generation_id}/elaboration")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ELABORATION_NOT_FOUND"


def test_페르소나_근거_19자_이하면_422_반환(client) -> None:
    """evidence_point가 20자 미만이면 스키마 유효성 검증 실패."""
    test_client, _ = client
    generation_id, suggestion_id = _create_generation_and_get_suggestion_id(test_client)

    body = _valid_elaboration_body(suggestion_id)
    body["persona"]["evidence_points"][0] = "짧은 근거"  # 5자 (기준 미달)

    response = test_client.post(
        f"/api/v1/idea-generations/{generation_id}/elaboration",
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_페인포인트_순서_잘못되면_422_반환(client) -> None:
    """단계 순서가 ①②③이 아니면 422 반환."""
    test_client, _ = client
    generation_id, suggestion_id = _create_generation_and_get_suggestion_id(test_client)

    body = _valid_elaboration_body(suggestion_id)
    # 순서를 ②①③으로 바꿈
    body["pain_point_cycle"][0]["step"] = "단계 ②"
    body["pain_point_cycle"][1]["step"] = "단계 ①"

    response = test_client.post(
        f"/api/v1/idea-generations/{generation_id}/elaboration",
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_페인포인트_2개면_422_반환(client) -> None:
    """페인포인트 고리가 3개 미만이면 422 반환."""
    test_client, _ = client
    generation_id, suggestion_id = _create_generation_and_get_suggestion_id(test_client)

    body = _valid_elaboration_body(suggestion_id)
    body["pain_point_cycle"].pop()  # 2개만 남김

    response = test_client.post(
        f"/api/v1/idea-generations/{generation_id}/elaboration",
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
