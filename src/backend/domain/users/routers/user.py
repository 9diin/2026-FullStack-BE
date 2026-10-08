from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.domain.users.schemas.user import UserCreate, UserLogin
from backend.domain.users.services.user import UserService

router = APIRouter(prefix="/auth", tags=["AUTH"])


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
def signIn(body: UserLogin, user_service: UserService = Depends(get_user_service)):
    print("body", body)
    # 로그인 API
    # - 클라이언트가 보낸 데이터는 UserLogin DTO를 통해 자동으로 검증됩니다.
    # - UserService의 sign_in 메서드를 호출하여 로그인 로직을 처리합니다.
    return user_service.sign_in(body)
