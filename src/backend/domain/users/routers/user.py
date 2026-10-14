from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.database import get_db
from backend.domain.users.schemas.user import UserCreate, UserLogin
from backend.domain.users.services.user import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    UserService,
)

router = APIRouter(prefix="/auth", tags=["AUTH"])
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def get_user_service(db: Session = Depends(get_db)):
    # UserService 객체를 생성하고 반환하는 함수
    return UserService(db)


@router.post("/sign-up", status_code=status.HTTP_201_CREATED)
def signUp(body: UserCreate, user_service: UserService = Depends(get_user_service)):

    print("body", body)
    # 회원가입 API
    # - 클라이언트가 보낸 데이터는 UserCreate DTO를 통해 자동으로 검증됩니다.
    # - UserService의 sign_up 메서드를 호출하여 회원가입 로직을 처리합니다.
    return user_service.sign_up(body)


@router.post("/sign-in")
def signIn(
    body: UserLogin,
    response: Response,
    user_service: UserService = Depends(get_user_service),
):
    login_response, refresh_token = user_service.sign_in(body)
    # HttpOnly는 프런트엔드 JavaScript가 refresh token을 읽지 못하게 합니다.
    # Secure는 HTTPS에서만 전송하고, SameSite=Lax는 다른 사이트의 요청 전송을 제한합니다.
    # refresh token은 응답 본문에 넣지 않아 스크립트나 일반 응답 로그에 노출되지 않게 합니다.
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
    )
    return login_response


@router.post("/refresh")
def refresh_access_token(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    user_service: UserService = Depends(get_user_service),
):
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh token 쿠키가 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = user_service.refresh_access_token(refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "status": status.HTTP_200_OK,
    }


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(response: Response) -> None:
    # 쿠키 Path를 로그인 때와 같게 지정해야 브라우저에서 같은 쿠키를 삭제합니다.
    # 이 stateless 구현의 sign-out은 현재 브라우저 쿠키만 삭제하며 이미 복사된 토큰은 만료 전까지 유효합니다.
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite="lax",
    )
