import bcrypt  # bcrypt 라이브러리를 직접 가져옵니다.
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.domain.users.models.user import User
from backend.domain.users.schemas.user import UserCreate, UserLogin


class UserService:
    def __init__(self, db: Session):
        # 라우터에서 Depends(get_db)를 통해 열어준 DB 세션을 UserService 클래스의 인스턴스 변수로 저장
        self.db = db

    # bcypyt, argon2 등 안전한 해싱 알고리즘을 사용하여 비밀번호를 해싱하는 로직을 구현해야 합니다.
    # bcypyt란 무엇인가요?
    # bcrypt는 사용자의 비밀번호를 안전하게 암호화(해싱)하기 위해 특별히 만들어진 알고리즘(공식)입니다.
    # 우리가 회원가입 때 입력받은 비밀번호(예: apple123)를 데이터베이스에 그대로 저장하면 절대 안 됩니다.
    # 만약 데이터베이스가 해킹당하면 회원들의 모든 비밀번호가 그대로 털리기 때문입니다.

    # 그렇다고 비밀번호를 양방향으로 암호화(잠그고 나중에 열어보는 방식)하면, 해커가 암호화 키까지 훔쳐갔을 때 모두 복호화되어 뚫리게 됩니다.
    # 그래서 비밀번호는 "아예 원래대로 되돌릴 수 없게 완전히 으깨버리는(해싱)" 방식을 사용하는데, 그 으깨는 방식 중 가장 안전하고 검증된 최고참 기술이 바로 bcrypt입니다.

    # bcrypt는 단방향 해싱 알고리즘으로, 입력된 비밀번호를 고정된 길이의 해시 값으로 변환합니다. 이 해시 값은 원래 비밀번호로 되돌릴 수 없으며, 동일한 입력에 대해 항상 동일한 해시 값을 생성합니다.
    # 또한, bcrypt는 솔트(salt)를 사용하여 동일한 비밀번호라도 매번 다른 해시 값을 생성하도록 하여 보안을 강화합니다.

    # 1) 단방향 암호화 (복구 불가능)
    # bcrypt는 비밀번호를 일종의 '분쇄기'에 넣고 갈아버립니다.
    # apple123을 넣으면 "$2b$12$EixZaYVK..."처럼 알아볼 수 없는 긴 문자열로 바뀝니다.
    # 특징: 이 결과물(...)을 보고 원래 비밀번호인 apple123이 무엇이었는지 절대 되돌릴 수 없습니다. (컴퓨터도 못 돌립니다.)

    # 2) 솔트(salt) 사용 (같은 비밀번호라도 매번 다른 해시 값 생성)
    # 만약 유저 A와 유저 B가 우연히 똑같이 비밀번호를 12345678로 설정했다고 해보겠습니다.
    # bcrypt는 내부적으로 랜덤한 솔트(salt)를 생성하여 비밀번호와 함께 해싱합니다.
    # 결과적으로 유저 A와 유저 B의 비밀번호 해시 값은 서로 다르게 생성됩니다. (즉, 해시 값이 같지 않습니다.)
    # 특징: 해커가 데이터베이스를 털어도, 같은 비밀번호라도 서로 다른 해시 값이 저장되어 있기 때문에, 무차별 대입 공격(Brute Force Attack)을 방지할 수 있습니다.
    # 만약 일반 암호화를 쓰면 두 사람의 DB 저장 값이 똑같이 보이기 때문에 해커가 "아, 이 사람들은 비밀번호가 똑같구나" 눈치채기 쉽습니다.
    # bcrypt는 암호화를 할 때 무작위의 의미 없는 문자열(Salt, 소금)을 랜덤으로 섞어줍니다.
    # 그 결과, 똑같은 12345678을 넣어도 가입할 때마다, 사람마다 매번 완전히 다른 모양의 해시 값이 만들어집니다. 해커가 데이터베이스를 통째로 털어도 분석하기가 거의 불가능해집니다.

    # 3) 느린 해싱 (무차별 대입 공격 방지)
    # bcrypt는 의도적으로 해싱 속도를 느리게 설계하여, 공격자가 무차별 대입 공격(Brute Force Attack)을 시도할 때 많은 시간이 걸리도록 합니다.
    # 해커들은 비밀번호를 털어간 뒤, 컴퓨터로 가능한 모든 문자열(1111, 1112, 1113...)을 엄청난 속도로 대입해 보며 맞추는 공격(브루트 포스)을 합니다.
    # 일반 암호화 알고리즘(예: MD5, SHA-256 등)은 컴퓨터가 1초에 수십억 개씩 계산할 수 있어서 해커가 금방 비밀번호를 뚫어냅니다.
    # bcrypt는 일부러 느리게 설계되어, 1초에 수천 번 정도만 해싱이 가능하게 합니다.
    # 정상적인 사용자 한 명이 로그인할 때는 0.1초도 안 걸려서 티가 안 나지만, 해커가 수십억 개의 비밀번호를 대입하려면 수십 년, 수백 년이 걸리게 만들어 컴퓨터를 뻗어버리게 만듭니다.

    # 설치 명령어: uv add passlib bcrypt
    def _hash_password(self, password: str) -> str:
        # 비밀번호 해싱 로직 구현 (예: bcrypt, argon2 등 사용)
        # 실제 구현에서는 안전한 해싱 알고리즘을 사용해야 합니다.
        # bcrypt의 72바이트 제한 에러를 막기 위한 안전장치 (72바이트 초과 시 자름)
        password_bytes = password.encode("utf-8")[:72]

        # 소금(Salt)을 생성하고 해시화
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)

        # DB에 저장하기 위해 문자열(utf-8)로 변환
        return hashed.decode("utf-8")

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
