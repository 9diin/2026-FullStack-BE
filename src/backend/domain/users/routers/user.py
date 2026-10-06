from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["AUTH"])


@router.post("/sign-up")
def signUp():
    return "회원가입 API 입니다."


@router.get("/sign-in")
def signIn():
    return "로그인 API 입니다."
