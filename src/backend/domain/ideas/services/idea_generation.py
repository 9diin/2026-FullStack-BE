from datetime import UTC, datetime
from pathlib import PurePath
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.domain.ideas.llm.idea_generator import (
    GeneratedIdeas,
    IdeaGenerationTimeout,
    IdeaGenerator,
    IdeaGeneratorAuthenticationError,
    IdeaGeneratorConfigurationError,
    IdeaGeneratorRateLimited,
    IdeaGeneratorUnavailable,
    InvalidIdeaGeneration,
)
from backend.domain.ideas.models.idea_generation import (
    IdeaGeneration,
    IdeaSelectionEvent,
    IdeaSuggestion,
    SourceFile,
)
from backend.domain.ideas.schemas.idea_generation import (
    IdeaGenerationContext,
    IdeaGenerationRequest,
    IdeaGenerationResponse,
    IdeaSelectionResponse,
    IdeaSuggestionResponse,
    SourceFileReference,
    SourceFileUploadResponse,
)
from backend.domain.users.models.user import User


class IdeaAPIError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


class IdeaGenerationService:
    def __init__(self, db: Session, generator: IdeaGenerator) -> None:
        self.db = db
        self.generator = generator

    def upload_source_file(
        self, user: User, filename: str | None, media_type: str | None, content: bytes
    ) -> SourceFileUploadResponse:
        if len(content) > settings.SOURCE_FILE_MAX_BYTES:
            maximum_size_mib = settings.SOURCE_FILE_MAX_BYTES / (1024 * 1024)
            raise IdeaAPIError(
                413,
                "FILE_TOO_LARGE",
                f"업로드 파일은 {maximum_size_mib:g} MiB를 초과할 수 없습니다.",
            )
        clean_filename = PurePath((filename or "").replace("\\", "/")).name.strip()
        if (
            not clean_filename
            or len(clean_filename) > 255
            or any(ord(character) < 32 for character in clean_filename)
            or PurePath(clean_filename).suffix.lower() != ".txt"
            or (media_type or "").split(";", 1)[0].strip().lower() != "text/plain"
        ):
            raise IdeaAPIError(
                415, "UNSUPPORTED_FILE_TYPE", "현재 TXT 형식의 참조 파일만 지원합니다."
            )
        try:
            extracted_text = content.decode("utf-8-sig").strip()
        except UnicodeDecodeError as exc:
            raise IdeaAPIError(
                415, "UNSUPPORTED_FILE_TYPE", "TXT 파일은 UTF-8 인코딩이어야 합니다."
            ) from exc
        if not extracted_text:
            raise IdeaAPIError(
                422, "SOURCE_FILE_EMPTY", "빈 파일은 분석할 수 없습니다."
            )

        source_file = SourceFile(
            user_id=user.id,
            filename=clean_filename,
            media_type="text/plain",
            size_bytes=len(content),
            extracted_text=extracted_text,
            status="ready",
        )
        self.db.add(source_file)
        self.db.commit()
        self.db.refresh(source_file)
        return SourceFileUploadResponse(
            id=source_file.id,
            filename=source_file.filename,
            media_type=source_file.media_type,
            size_bytes=source_file.size_bytes,
            status="ready",
        )

    def generate(
        self, user: User | None, request: IdeaGenerationRequest
    ) -> IdeaGenerationResponse:
        if request.project_id is not None:
            raise IdeaAPIError(
                403,
                "FORBIDDEN",
                "현재 프로젝트 권한을 확인할 수 없어 프로젝트 요청을 "
                "처리할 수 없습니다.",
            )

        source_files: list[SourceFile] = []
        if request.source_file_ids:
            if user is None:
                raise IdeaAPIError(
                    401,
                    "AUTHENTICATION_REQUIRED",
                    "참조 파일을 사용하려면 로그인해 주세요.",
                )
            source_files = (
                self.db.query(SourceFile)
                .filter(
                    SourceFile.id.in_(request.source_file_ids),
                    SourceFile.user_id == user.id,
                    SourceFile.project_id.is_(None),
                )
                .all()
            )
            if len(source_files) != len(request.source_file_ids):
                raise IdeaAPIError(
                    404,
                    "SOURCE_FILE_NOT_FOUND",
                    "참조 파일을 찾을 수 없습니다.",
                )
            if any(source_file.status != "ready" for source_file in source_files):
                raise IdeaAPIError(
                    422,
                    "SOURCE_FILE_NOT_READY",
                    "아직 분석할 수 없는 참조 파일이 포함되어 있습니다.",
                )

        source_text_length = sum(len(item.extracted_text) for item in source_files)
        if source_text_length > settings.IDEA_SOURCE_MAX_CHARS:
            raise IdeaAPIError(
                422,
                "SOURCE_CONTENT_TOO_LONG",
                "참조 파일의 전체 텍스트가 분석 한도를 초과합니다.",
            )

        try:
            generated = self.generator.generate(request.prompt, source_files)
        except IdeaGeneratorAuthenticationError as exc:
            raise IdeaAPIError(
                503,
                "LLM_AUTHENTICATION_ERROR",
                "Gemini API 키 인증에 실패했습니다. Google AI Studio에서 Gemini Developer API 키를 "
                "발급해 GEMINI_API_KEY에 설정한 뒤 백엔드 서버를 재시작해 주세요. "
                "서비스 계정에 연결된 Google Cloud API 키는 Gemini API에서 지원되지 않습니다.",
            ) from exc
        except IdeaGeneratorConfigurationError as exc:
            raise IdeaAPIError(
                503,
                "LLM_CONFIGURATION_ERROR",
                "Gemini API 인증·모델·요청 형식이 올바른지 확인해 주세요. "
                "상세 오류는 백엔드 로그에서 확인할 수 있습니다.",
            ) from exc
        except IdeaGeneratorRateLimited as exc:
            raise IdeaAPIError(
                429,
                "LLM_QUOTA_EXCEEDED",
                "Gemini API 요청 한도를 초과했습니다. Google AI Studio에서 "
                "사용량·결제 설정을 확인하거나 한도 초기화 후 다시 시도해 주세요.",
            ) from exc
        except IdeaGeneratorUnavailable as exc:
            raise IdeaAPIError(
                503, "LLM_UNAVAILABLE", "아이디어 생성 서비스를 사용할 수 없습니다."
            ) from exc
        except IdeaGenerationTimeout as exc:
            raise IdeaAPIError(
                504, "GENERATION_TIMEOUT", "아이디어 생성 시간이 초과되었습니다."
            ) from exc
        except InvalidIdeaGeneration as exc:
            raise IdeaAPIError(
                502,
                "LLM_INVALID_RESPONSE",
                "유효한 아이디어 결과를 생성하지 못했습니다.",
            ) from exc

        self._validate_generated(generated)
        if user is None:
            generation_id = uuid4()
            return IdeaGenerationResponse(
                generation_id=generation_id,
                created_at=datetime.now(UTC),
                persisted=False,
                context=IdeaGenerationContext(
                    source_files=[],
                    focus_items=generated.focus_items,
                ),
                suggestions=[
                    IdeaSuggestionResponse(
                        id=str(uuid4()),
                        title=suggestion.title.strip(),
                        details=[detail.strip() for detail in suggestion.details],
                    )
                    for suggestion in generated.suggestions
                ],
            )

        generation = IdeaGeneration(
            user_id=user.id,
            project_id=request.project_id,
            prompt=request.prompt,
            interest_categories=list(dict.fromkeys(generated.interest_categories)),
            suggestions=[
                IdeaSuggestion(
                    id=uuid4(),
                    position=position,
                    title=suggestion.title.strip(),
                    details=[detail.strip() for detail in suggestion.details],
                )
                for position, suggestion in enumerate(generated.suggestions)
            ],
        )
        self.db.add(generation)
        self.db.commit()
        self.db.refresh(generation)

        return IdeaGenerationResponse(
            generation_id=generation.id,
            created_at=generation.created_at,
            context=IdeaGenerationContext(
                source_files=[
                    SourceFileReference(
                        id=file.id, filename=file.filename, media_type=file.media_type
                    )
                    for file in source_files
                ],
                focus_items=generated.focus_items,
            ),
            suggestions=[
                IdeaSuggestionResponse(
                    id=str(suggestion.id),
                    title=suggestion.title,
                    details=suggestion.details,
                )
                for suggestion in generation.suggestions
            ],
        )

    def select_idea(
        self, user: User, generation_id: UUID, selected_idea_id: UUID
    ) -> IdeaSelectionResponse:
        generation = (
            self.db.query(IdeaGeneration)
            .filter(
                IdeaGeneration.id == generation_id,
                IdeaGeneration.user_id == user.id,
            )
            .first()
        )
        if generation is None:
            raise IdeaAPIError(
                404, "GENERATION_NOT_FOUND", "도출 결과를 찾을 수 없습니다."
            )

        selected = next(
            (
                suggestion
                for suggestion in generation.suggestions
                if suggestion.id == selected_idea_id
            ),
            None,
        )
        if selected is None:
            raise IdeaAPIError(
                404, "IDEA_NOT_FOUND", "선택한 아이디어를 찾을 수 없습니다."
            )

        selected_at = datetime.now(UTC)
        for suggestion in generation.suggestions:
            suggestion.selected_at = (
                selected_at if suggestion.id == selected_idea_id else None
            )
        self.db.add(
            IdeaSelectionEvent(
                user_id=user.id,
                generation_id=generation.id,
                suggestion_id=selected.id,
                selected_at=selected_at,
            )
        )
        self.db.commit()
        return IdeaSelectionResponse(
            generation_id=generation.id,
            selected_idea_id=selected.id,
            selected_at=selected_at,
        )

    @staticmethod
    def _validate_generated(generated: GeneratedIdeas) -> None:
        if not generated.focus_items or any(
            not item.strip() for item in generated.focus_items
        ):
            raise IdeaAPIError(
                502,
                "LLM_INVALID_RESPONSE",
                "유효한 아이디어 결과를 생성하지 못했습니다.",
            )
        if len(generated.suggestions) != 3:
            raise IdeaAPIError(
                502,
                "LLM_INVALID_RESPONSE",
                "유효한 아이디어 결과를 생성하지 못했습니다.",
            )
        titles = [item.title.strip().casefold() for item in generated.suggestions]
        if any(not title for title in titles) or len(titles) != len(set(titles)):
            raise IdeaAPIError(
                502,
                "LLM_INVALID_RESPONSE",
                "유효한 아이디어 결과를 생성하지 못했습니다.",
            )
        if any(
            not item.details or any(not detail.strip() for detail in item.details)
            for item in generated.suggestions
        ):
            raise IdeaAPIError(
                502,
                "LLM_INVALID_RESPONSE",
                "유효한 아이디어 결과를 생성하지 못했습니다.",
            )
