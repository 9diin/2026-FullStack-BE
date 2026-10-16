from collections.abc import Generator
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.genai._gaos.errors import GenAiDefaultError
from google.genai._gaos.lib.compat_errors import BadRequestError
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.config import settings
from backend.core.cors import CorsFastAPI
from backend.core.database import Base, get_db
from backend.domain.ideas.errors import register_idea_error_handlers
from backend.domain.ideas.llm.idea_generator import (
    GeminiIdeaGenerator,
    GeneratedIdeas,
    IdeaGenerationTimeout,
    IdeaGeneratorConfigurationError,
    IdeaGeneratorRateLimited,
    InvalidIdeaGeneration,
)
from backend.domain.ideas.models.idea_generation import (
    IdeaGeneration,
    IdeaSelectionEvent,
    IdeaSuggestion,
    SourceFile,
)
from backend.domain.ideas.rate_limit import anonymous_generation_rate_limiter
from backend.domain.ideas.routers.idea_generations import (
    get_idea_generator,
    router,
)
from backend.domain.users.models.email_verification import (
    EmailVerification,  # noqa: F401
)
from backend.domain.users.models.user import User
from backend.domain.users.models.user_profile import UserProfile  # noqa: F401
from backend.domain.users.routers.dependencies import (
    get_current_user,
    get_optional_current_user,
)


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


class FakeIdeaGenerator:
    def __init__(self) -> None:
        self.received_prompt: str | None = None
        self.received_sources: list[SourceFile] | None = None

    def generate(
        self, prompt: str, source_documents: list[SourceFile]
    ) -> GeneratedIdeas:
        self.received_prompt = prompt
        self.received_sources = source_documents
        return GeneratedIdeas(
            focus_items=["초기 고객", "검증 방법"],
            interest_categories=["교육"],
            suggestions=[
                {"title": "개인 맞춤 학습 코치", "details": ["진단", "학습 추천"]},
                {"title": "학교 연계 튜터 매칭", "details": ["수요 연결", "성과 확인"]},
                {
                    "title": "학습 자료 구독 서비스",
                    "details": ["자료 큐레이션", "이용 분석"],
                },
            ],
        )


class InvalidResponseGenerator:
    def generate(
        self, prompt: str, source_documents: list[SourceFile]
    ) -> GeneratedIdeas:
        raise InvalidIdeaGeneration


class InvalidConfigurationGenerator:
    def generate(
        self, prompt: str, source_documents: list[SourceFile]
    ) -> GeneratedIdeas:
        raise IdeaGeneratorConfigurationError


class RateLimitedIdeaGenerator:
    def generate(
        self, prompt: str, source_documents: list[SourceFile]
    ) -> GeneratedIdeas:
        raise IdeaGeneratorRateLimited


@pytest.fixture
def client() -> Generator[
    tuple[TestClient, sessionmaker[Session], FakeIdeaGenerator], None, None
]:
    anonymous_generation_rate_limiter.reset()
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
    generator = FakeIdeaGenerator()

    def override_db() -> Generator[Session, None, None]:
        with test_session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_current_user] = lambda: user
    app.dependency_overrides[get_idea_generator] = lambda: generator

    with TestClient(app) as test_client:
        yield test_client, test_session_factory, generator
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_generate_persists_prompt_categories_and_three_ideas(client) -> None:
    test_client, session_factory, generator = client

    response = test_client.post(
        "/api/v1/idea-generations",
        json={"prompt": "  교육 현장의 반복 업무를 줄이고 싶어요.  "},
    )

    assert response.status_code == 200
    body = response.json()
    assert generator.received_prompt == "교육 현장의 반복 업무를 줄이고 싶어요."
    assert body["context"]["source_files"] == []
    assert len(body["suggestions"]) == 3
    assert body["persisted"] is True
    assert body["context"]["focus_items"] == ["초기 고객", "검증 방법"]

    with session_factory() as db:
        generation = db.query(IdeaGeneration).one()
        assert generation.prompt == "교육 현장의 반복 업무를 줄이고 싶어요."
        assert generation.interest_categories == ["교육"]
        assert db.query(IdeaSuggestion).count() == 3


def test_anonymous_generation_returns_three_ideas_without_persisting(client) -> None:
    test_client, session_factory, generator = client
    test_client.app.dependency_overrides[get_optional_current_user] = lambda: None

    response = test_client.post(
        "/api/v1/idea-generations",
        json={"prompt": "로그인 없이 아이디어를 미리 확인합니다."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] is False
    assert len(body["suggestions"]) == 3
    assert generator.received_prompt == "로그인 없이 아이디어를 미리 확인합니다."
    with session_factory() as db:
        assert db.query(IdeaGeneration).count() == 0
        assert db.query(IdeaSuggestion).count() == 0


def test_anonymous_generation_is_limited_to_five_requests_per_hour(client) -> None:
    test_client, session_factory, _generator = client
    test_client.app.dependency_overrides[get_optional_current_user] = lambda: None

    responses = [
        test_client.post(
            "/api/v1/idea-generations",
            json={"prompt": f"익명 요청 {index}"},
        )
        for index in range(6)
    ]

    assert [response.status_code for response in responses] == [
        200,
        200,
        200,
        200,
        200,
        429,
    ]
    assert responses[-1].json()["error"]["code"] == "ANONYMOUS_RATE_LIMITED"
    with session_factory() as db:
        assert db.query(IdeaGeneration).count() == 0


def test_upload_and_generation_only_use_the_authenticated_users_file(client) -> None:
    test_client, _session_factory, generator = client
    uploaded = test_client.post(
        "/api/v1/source-files",
        files={"file": ("interviews.txt", "사용자 인터뷰 내용", "text/plain")},
    )

    assert uploaded.status_code == 201
    file_info = uploaded.json()
    generated = test_client.post(
        "/api/v1/idea-generations",
        json={
            "prompt": "인터뷰에서 반복된 문제를 바탕으로 아이디어를 제안해 주세요.",
            "source_file_ids": [file_info["id"]],
        },
    )

    assert generated.status_code == 200
    assert generator.received_sources is not None
    assert generator.received_sources[0].filename == "interviews.txt"
    assert generated.json()["context"]["source_files"] == [
        {
            "id": file_info["id"],
            "filename": "interviews.txt",
            "media_type": "text/plain",
        }
    ]


def test_other_users_source_file_is_not_revealed_or_analyzed(client) -> None:
    test_client, session_factory, generator = client
    with session_factory() as db:
        other_user = User(
            id=2,
            email="other@example.com",
            password="not-used",
            terms_agreed=True,
            privacy_agreed=True,
            marketing_agreed=False,
        )
        source_file = SourceFile(
            user_id=2,
            filename="private.txt",
            media_type="text/plain",
            size_bytes=15,
            extracted_text="private material",
            status="ready",
        )
        db.add_all([other_user, source_file])
        db.commit()
        file_id = source_file.id

    response = test_client.post(
        "/api/v1/idea-generations",
        json={
            "prompt": "이 파일의 소유권 검증을 수행합니다.",
            "source_file_ids": [str(file_id)],
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SOURCE_FILE_NOT_FOUND"
    assert generator.received_prompt is None


def test_invalid_model_result_is_not_returned_as_success(client) -> None:
    test_client, _session_factory, _generator = client
    test_client.app.dependency_overrides[get_idea_generator] = lambda: (
        InvalidResponseGenerator()
    )

    response = test_client.post(
        "/api/v1/idea-generations",
        json={"prompt": "잘못된 모델 응답은 오류로 처리되어야 합니다."},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_INVALID_RESPONSE"
    assert "suggestions" not in response.json()


def test_selection_is_persisted_for_trend_analysis(client) -> None:
    test_client, session_factory, _generator = client
    created = test_client.post(
        "/api/v1/idea-generations",
        json={"prompt": "교육 아이디어를 구상하고 싶습니다."},
    ).json()
    selected_id = created["suggestions"][1]["id"]

    response = test_client.post(
        f"/api/v1/idea-generations/{created['generation_id']}/selection",
        json={"selected_idea_id": selected_id},
    )

    assert response.status_code == 200
    assert response.json()["selected_idea_id"] == selected_id
    with session_factory() as db:
        suggestions = db.query(IdeaSuggestion).order_by(IdeaSuggestion.position).all()
        assert [suggestion.selected_at is not None for suggestion in suggestions] == [
            False,
            True,
            False,
        ]
        assert db.query(IdeaSelectionEvent).count() == 1


def test_duplicate_source_ids_are_rejected_with_stable_error(client) -> None:
    test_client, _session_factory, _generator = client
    file_id = str(UUID("c98c97a1-322d-4ed9-9951-c28cf8128fd4"))

    response = test_client.post(
        "/api/v1/idea-generations",
        json={
            "prompt": "중복된 파일 요청을 검증합니다.",
            "source_file_ids": [file_id, file_id],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]


def test_openapi_describes_stable_error_response(client) -> None:
    test_client, _session_factory, _generator = client

    schema = test_client.get("/openapi.json").json()
    generation_responses = schema["paths"]["/api/v1/idea-generations"]["post"][
        "responses"
    ]

    assert "422" in generation_responses
    assert "APIErrorResponse" in str(generation_responses["422"])


def test_missing_bearer_credentials_allow_ephemeral_generation(client) -> None:
    test_client, _session_factory, _generator = client
    test_client.app.dependency_overrides.pop(get_current_user)
    test_client.app.dependency_overrides.pop(get_optional_current_user)

    response = test_client.post(
        "/api/v1/idea-generations",
        json={"prompt": "비로그인 아이디어 생성 결과는 저장되지 않습니다."},
    )

    assert response.status_code == 200
    assert response.json()["persisted"] is False
    assert len(response.json()["suggestions"]) == 3


def test_missing_llm_key_returns_unavailable_error(client, monkeypatch) -> None:
    test_client, _session_factory, _generator = client
    test_client.app.dependency_overrides.pop(get_idea_generator)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)

    response = test_client.post(
        "/api/v1/idea-generations",
        json={"prompt": "키 미설정 상태의 오류 응답을 확인합니다."},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_UNAVAILABLE"
    assert "request_id" in response.json()["error"]


def test_quota_exceeded_returns_actionable_rate_limit_error(client) -> None:
    test_client, _session_factory, _generator = client
    test_client.app.dependency_overrides[get_idea_generator] = lambda: (
        RateLimitedIdeaGenerator()
    )

    response = test_client.post(
        "/api/v1/idea-generations",
        json={"prompt": "한도 초과 응답을 확인합니다."},
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "LLM_QUOTA_EXCEEDED"
    assert "Google AI Studio" in response.json()["error"]["message"]


def test_cors_headers_are_added_to_unhandled_server_errors() -> None:
    app = CorsFastAPI(cors_origins=["http://localhost:3000"])

    @app.get("/failure")
    def fail() -> None:
        raise RuntimeError("unexpected failure")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get(
            "/failure", headers={"Origin": "http://localhost:3000"}
        )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_allows_frontend_loopback_ip_origin() -> None:
    app = CorsFastAPI(cors_origins=["http://localhost:3000", "http://127.0.0.1:3000"])

    with TestClient(app) as test_client:
        response = test_client.options(
            "/api/v1/idea-generations",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


def test_gemini_adapter_requests_and_validates_structured_output(monkeypatch) -> None:
    generated = GeneratedIdeas(
        focus_items=["초기 사용자", "검증 지표"],
        interest_categories=["교육"],
        suggestions=[
            {"title": "맞춤형 학습도우미", "details": ["학습 진단", "개인별 추천"]},
            {"title": "학부모 학습 대시보드", "details": ["진도 공유", "상담 연결"]},
            {"title": "교사용 자료 큐레이션", "details": ["자료 탐색", "수업 활용"]},
        ],
    )
    captured: dict[str, object] = {}

    class FakeInteractions:
        def create(self, **kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(output_text=generated.model_dump_json())

    class FakeClient:
        interactions = FakeInteractions()

        def __init__(self, **kwargs: object) -> None:
            captured["client_options"] = kwargs

        def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(settings, "GEMINI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(
        "backend.domain.ideas.llm.idea_generator.genai.Client", FakeClient
    )

    result = GeminiIdeaGenerator().generate("교육 아이디어", [])

    assert result == generated
    assert captured["timeout"] == min(settings.LLM_TIMEOUT_SECONDS, 30.0)
    assert captured["client_options"]["http_options"].timeout == 30_000
    retry_options = captured["client_options"]["http_options"].retry_options
    assert retry_options.attempts == 1
    assert 429 not in retry_options.http_status_codes
    assert captured["model"] == settings.GEMINI_MODEL
    assert captured["response_format"]["mime_type"] == "application/json"
    assert "$defs" not in captured["response_format"]["schema"]
    assert "$ref" not in str(captured["response_format"]["schema"])
    assert captured["store"] is False
    assert captured["closed"] is True


def test_interactions_api_bad_request_is_mapped_to_configuration_error(
    monkeypatch,
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
        "backend.domain.ideas.llm.idea_generator.genai.Client", FakeClient
    )

    with pytest.raises(IdeaGeneratorConfigurationError):
        GeminiIdeaGenerator().generate("교육 아이디어", [])


def test_gemini_timeout_maps_to_generation_timeout(monkeypatch) -> None:
    class FakeInteractions:
        def create(self, **_kwargs: object) -> None:
            raise httpx.ReadTimeout("timeout")

    class FakeClient:
        interactions = FakeInteractions()

        def __init__(self, **_kwargs: object) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(settings, "GEMINI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(
        "backend.domain.ideas.llm.idea_generator.genai.Client", FakeClient
    )

    with pytest.raises(IdeaGenerationTimeout):
        GeminiIdeaGenerator().generate("교육 아이디어", [])


def test_gemini_rejected_configuration_is_not_reported_as_network_failure(
    monkeypatch,
) -> None:
    class FakeInteractions:
        def create(self, **_kwargs: object) -> None:
            raise provider_error(404, "model not found")

    class FakeClient:
        interactions = FakeInteractions()

        def __init__(self, **_kwargs: object) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(settings, "GEMINI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(
        "backend.domain.ideas.llm.idea_generator.genai.Client", FakeClient
    )

    with pytest.raises(IdeaGeneratorConfigurationError):
        GeminiIdeaGenerator().generate("교육 아이디어", [])


def test_gemini_400_retries_with_supported_fallback_model(monkeypatch) -> None:
    generated = GeneratedIdeas(
        focus_items=["초기 사용자", "검증 지표"],
        interest_categories=["교육"],
        suggestions=[
            {"title": "맞춤형 학습도우미", "details": ["학습 진단", "개인별 추천"]},
            {"title": "학부모 학습 대시보드", "details": ["진도 공유", "상담 연결"]},
            {"title": "교사용 자료 큐레이션", "details": ["자료 탐색", "수업 활용"]},
        ],
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
        "backend.domain.ideas.llm.idea_generator.genai.Client", FakeClient
    )

    result = GeminiIdeaGenerator().generate("교육 아이디어", [])

    assert result == generated
    assert attempted_models == [
        "invalid-configured-model",
        "gemini-3.8-flash",
    ]


def test_gemini_429_retries_with_current_fallback_model(monkeypatch) -> None:
    generated = GeneratedIdeas(
        focus_items=["초기 사용자", "검증 지표"],
        interest_categories=["교육"],
        suggestions=[
            {"title": "맞춤형 학습도우미", "details": ["학습 진단", "개인별 추천"]},
            {"title": "학부모 학습 대시보드", "details": ["진도 공유", "상담 연결"]},
            {"title": "교사용 자료 큐레이션", "details": ["자료 탐색", "수업 활용"]},
        ],
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
        "backend.domain.ideas.llm.idea_generator.genai.Client", FakeClient
    )

    assert GeminiIdeaGenerator().generate("교육 아이디어", []) == generated
    assert attempted_models == ["quota-limited-model", "gemini-3.8-flash"]


def test_gemini_429_without_available_fallback_raises_rate_limit(monkeypatch) -> None:
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
        "backend.domain.ideas.llm.idea_generator.genai.Client", FakeClient
    )

    with pytest.raises(IdeaGeneratorRateLimited):
        GeminiIdeaGenerator().generate("교육 아이디어", [])


def test_gemini_rejects_malformed_base_url_before_request(monkeypatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(
        settings,
        "GEMINI_BASE_URL",
        "GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta",
    )

    with pytest.raises(IdeaGeneratorConfigurationError):
        GeminiIdeaGenerator().generate("교육 아이디어", [])


def test_gemini_configuration_error_has_actionable_api_response(client) -> None:
    test_client, _session_factory, _generator = client
    test_client.app.dependency_overrides[get_idea_generator] = lambda: (
        InvalidConfigurationGenerator()
    )

    response = test_client.post(
        "/api/v1/idea-generations",
        json={"prompt": "설정 오류는 사용자에게 안내되어야 합니다."},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_CONFIGURATION_ERROR"
    assert "요청 형식" in response.json()["error"]["message"]
