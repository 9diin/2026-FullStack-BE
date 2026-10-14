from fastapi import APIRouter

router = APIRouter(prefix="/user", tags=["USER"])


@router.get("/profile")
def get_user_profile():
    return "유저 프로필 조회"


# 회원가입 시, 유저 프로필도 함께 생성
@router.post("/profile")
def create_user_profile():
    return "유저 프로필 생성"


# 유저 프로필 수정
@router.patch("/profile")
def update_user_profile():
    return "유저 프로필 수정"


# 회원탈퇴
@router.delete("")
def withdraw_user():
    return "회원 탈퇴"
