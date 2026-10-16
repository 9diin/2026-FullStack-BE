from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp


class CorsFastAPI(FastAPI):
    def __init__(self, *, cors_origins: list[str], **kwargs: Any) -> None:
        self._cors_origins = cors_origins
        super().__init__(**kwargs)

    def build_middleware_stack(self) -> ASGIApp:
        app = super().build_middleware_stack()
        return CORSMiddleware(
            app=app,
            allow_origins=self._cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
