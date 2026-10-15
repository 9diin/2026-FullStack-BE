import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.domain.ideas.services.idea_generation import IdeaAPIError

logger = logging.getLogger(__name__)
IDEA_PATH_PREFIXES = ("/api/v1/idea-generations", "/api/v1/source-files")


def register_idea_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(IdeaAPIError)
    async def handle_idea_error(_request: Request, exc: IdeaAPIError) -> JSONResponse:
        request_id = str(uuid4())
        logger.info("Idea API error code=%s request_id=%s", exc.code, request_id)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": request_id,
                }
            },
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_idea_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        if not request.url.path.startswith(IDEA_PATH_PREFIXES):
            return await request_validation_exception_handler(request, exc)
        request_id = str(uuid4())
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "요청 데이터가 올바르지 않습니다.",
                    "request_id": request_id,
                }
            },
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(Exception)
    async def handle_idea_unexpected_error(
        request: Request, exc: Exception
    ) -> JSONResponse:
        request_id = str(uuid4())
        if not request.url.path.startswith(IDEA_PATH_PREFIXES):
            logger.error("Unexpected API failure request_id=%s", request_id)
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error"},
            )
        logger.error("Unexpected idea API failure request_id=%s", request_id)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "요청을 처리하지 못했습니다.",
                    "request_id": request_id,
                }
            },
            headers={"X-Request-ID": request_id},
        )
