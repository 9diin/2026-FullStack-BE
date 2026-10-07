from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.domain.users.models.user import User
from backend.domain.users.schemas.user import UserCreate, UserLogin


class UserService:
    def __init__(self, db: Session):
        # 라우터에서 Depends(get_db)를 통해 열어준 DB 세션을 UserService 클래스의 인스턴스 변수로 저장
        self.db = db

    def _hash_password(self, password: str) -> str:
        # 비밀번호 해싱 로직 구현 (예: bcrypt, argon2 등 사용)
        # 실제 구현에서는 안전한 해싱 알고리즘을 사용해야 합니다.
        return password  # 단순 예시로 원래 비밀번호를 반환 (실제 구현에서는 해싱된 비밀번호를 반환해야 함)

    def sign_up(self, body: UserCreate):
        # 회원가입 로직 구현
        # 예: 사용자 정보를 데이터베이스에 저장하고, 비밀번호를 해싱하여 저장하는 등의 작업 수행

        # 1. 이미 가입된 이메일인지 검증
        # Supabase(DB)에서 이미 가입된 이메일인지 조회
        # # (실제 SQLAlchemy 쿼리 예시: existing_user = self.db.query(User).filter(User.email == user_in.email).first())
        exisiting_user = self.db.query(User).filter(User.email == body.email).first()
        if exisiting_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이미 가입된 이메일입니다.",
            )

        # 2. 필수 약관 및 개인정보 처리방침 동의 여부 검증
        if not body.terms_agreed or not body.privacy_agreed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="필수 약관 및 개인정보 처리방침에 동의해야 합니다.",
            )

        # 3. 비밀번호 해싱
        hashed_password = self._hash_password(body.password)

        # 4. 데이터베이스(Supabase)에 저장할 User 모델 객체 생성
        new_user = User(
            email=body.email,
            password=hashed_password,  # 평문이 아닌 해시된 비밀번호 저장!
            terms_agreed=body.terms_agreed,
            privacy_agreed=body.privacy_agreed,
            marketing_agreed=body.marketing_agreed,
        )

        # 5. DB에 추가하고 변경사항 커밋(반영)
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)  # DB에 저장되면서 자동 생성된 ID 등을 객체에 갱신

        return {"message": "회원가입이 완료되었습니다.", "email": new_user.email}

    def sign_in(self, body: UserLogin):
        # 로그인 로직 구현
        # 예: 사용자 인증 정보를 검증하고, 토큰을 발급하는 등의 작업 수행

        # 1. 이메일과 비밀번호 검증
        # 2. 인증 성공 시 토큰 발급
        return {"message": "로그인이 완료되었습니다."}
