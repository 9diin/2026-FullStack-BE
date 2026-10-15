from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.database import get_db
from backend.domain.ideas.llm.elaboration_generator import (
    GeminiIdeaElaborationGenerator,
    IdeaElaborationGenerator,
)
from backend.domain.ideas.llm.idea_generator import GeminiIdeaGenerator, IdeaGenerator
from backend.domain.ideas.schemas.idea_generation import (
    APIErrorResponse,
    IdeaGenerationRequest,
    IdeaGenerationResponse,
    IdeaSelectionRequest,
    IdeaSelectionResponse,
    SourceFileUploadResponse,
)
from backend.domain.ideas.schemas.idea_elaboration import (
    ElaborationRequest,
    ElaborationResponse,
)
from backend.domain.ideas.services.idea_generation import IdeaGenerationService
from backend.domain.ideas.services.idea_elaboration import IdeaElaborationService
from backend.domain.users.models.user import User
from backend.domain.users.routers.dependencies import get_current_user

router = APIRouter(tags=["IDEA GENERATION"])
ERROR_RESPONSES = {
    code: {"model": APIErrorResponse, "description": description}
    for code, description in {
        400: "잘못된 요청입니다.",
        401: "인증이 필요합니다.",
        403: "접근 권한이 없습니다.",
        404: "리소스를 찾을 수 없습니다.",
        413: "파일 크기 제한을 초과했습니다.",
        415: "지원하지 않는 파일 형식입니다.",
        422: "요청 또는 참조 파일을 검증할 수 없습니다.",
        500: "내부 오류입니다.",
        502: "LLM 결과가 유효하지 않습니다.",
        503: "LLM 서비스를 사용할 수 없습니다.",
        504: "LLM 응답 시간이 초과되었습니다.",
    }.items()
}


def get_idea_generator() -> IdeaGenerator:
    return GeminiIdeaGenerator()


def get_idea_generation_service(
    db: Session = Depends(get_db),
    generator: IdeaGenerator = Depends(get_idea_generator),
) -> IdeaGenerationService:
    return IdeaGenerationService(db, generator)





def get_idea_elaboration_generator() -> IdeaElaborationGenerator:
    return GeminiIdeaElaborationGenerator()


def get_idea_elaboration_service(
    db: Session = Depends(get_db),
    generator: IdeaElaborationGenerator = Depends(get_idea_elaboration_generator),
) -> IdeaElaborationService:
    return IdeaElaborationService(db, generator)


@router.post(
    "/source-files",
    response_model=SourceFileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
async def upload_source_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    service: IdeaGenerationService = Depends(get_idea_generation_service),
) -> SourceFileUploadResponse:
    content = await file.read(settings.SOURCE_FILE_MAX_BYTES + 1)
    return service.upload_source_file(
        current_user, file.filename, file.content_type, content
    )


@router.post(
    "/idea-generations",
    response_model=IdeaGenerationResponse,
    status_code=status.HTTP_200_OK,
    responses=ERROR_RESPONSES,
)
def create_idea_generation(
    body: IdeaGenerationRequest,
    current_user: User = Depends(get_current_user),
    service: IdeaGenerationService = Depends(get_idea_generation_service),
) -> IdeaGenerationResponse:
    return service.generate(current_user, body)


@router.post(
    "/idea-generations/{generation_id}/selection",
    response_model=IdeaSelectionResponse,
    responses=ERROR_RESPONSES,
)
def select_idea(
    generation_id: UUID,
    body: IdeaSelectionRequest,
    current_user: User = Depends(get_current_user),
    service: IdeaGenerationService = Depends(get_idea_generation_service),
) -> IdeaSelectionResponse:
    return service.select_idea(current_user, generation_id, body.selected_idea_id)


@router.post(
    "/idea-generations/{generation_id}/elaboration",
    response_model=ElaborationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        **ERROR_RESPONSES,
        409: {"model": APIErrorResponse, "description": "이미 구체화 데이터가 존재합니다."},
    },
    summary="아이디어 구체화 데이터 생성",
    description=(
        "선택한 아이디어 제안의 문제인식·페르소나·3대 페인포인트 악순환 고리·AI 코칭 데이터를 "
        "저장합니다. 동일 generation_id에 대해 최초 1회만 생성 가능합니다."
    ),
)
def create_elaboration(
    generation_id: UUID,
    body: ElaborationRequest,
    current_user: User = Depends(get_current_user),
    service: IdeaElaborationService = Depends(get_idea_elaboration_service),
) -> ElaborationResponse:
    return service.create_elaboration(current_user, generation_id, body)


@router.get(
    "/idea-generations/{generation_id}/elaboration",
    response_model=ElaborationResponse,
    responses=ERROR_RESPONSES,
    summary="아이디어 구체화 데이터 조회",
    description="generation_id에 연결된 구체화 데이터를 반환합니다.",
)
def get_elaboration(
    generation_id: UUID,
    current_user: User = Depends(get_current_user),
    service: IdeaElaborationService = Depends(get_idea_elaboration_service),
) -> ElaborationResponse:
    return service.get_elaboration(current_user, generation_id)
