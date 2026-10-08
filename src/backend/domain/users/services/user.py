from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, status
from jose import jwt
from sqlalchemy.orm import Session

from backend.domain.users.models.user import User
from backend.domain.users.schemas.user import UserCreate, UserLogin

# 설정값 (실제로는 환경변수나 설정 파일에서 관리합니다)
SECRET_KEY = "your-super-secret-key"
ALGORITHM = "HS256"
BCRYPT_MAX_PASSWORD_BYTES = 72


class UserService:
    def __init__(self, db: Session) -> None:
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

    # uv add passlib bcrypt
    def _hash_password(self, password: str) -> str:
        # 비밀번호 해싱 로직 구현 (예: bcrypt, argon2 등 사용)
        # 실제 구현에서는 안전한 해싱 알고리즘을 사용해야 합니다.
        # bcrypt의 72바이트 제한 에러를 막기 위한 안전장치 (72바이트 초과 시 자름)
        password_bytes = password.encode("utf-8")[:BCRYPT_MAX_PASSWORD_BYTES]

        # 소금(Salt)을 생성하고 해시화
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)

        # DB에 저장하기 위해 문자열(utf-8)로 변환
        return hashed.decode("utf-8")

    # 토큰 생성 함수
    # 설치 명령어: uv add python-jose
    def _create_token(self, data, expires_delta: timedelta) -> str:
        # 데이터의 timedelta 만료 시간을 받아 안전하게 JWT를 생성합니다.
        to_encode = data.copy()

        # 타임존(UTC)이 포함된 현재 시간에 timedelta를 더해 만료 시간 계산
        expire = datetime.now(timezone.utc) + expires_delta

        # JWT 표준 클레임인 'exp'(Expiration)에 만료 시간 반영
        to_encode.update({"exp": expire})

        # JWT 인코딩 후 문자열로 반환
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    def sign_up(self, body: UserCreate):
        # 회원가입 로직 구현
        # 예: 사용자 정보를 데이터베이스의 저장하고, 비밀번호를 해싱하여 저장하는 등의 작업 수행

        # 1. 이미 가입된 이메일인지 검증
        # Supabase(DB)에세 이미 가입된 이메일인지 조회
        existing_user = self.db.query(User).filter(User.email == body.email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이미 가입된 이메일입니다.",
            )

        # 2. 필수 약관 및 개인정보처리방침 동의 여부 검증
        if not body.terms_agreed or not body.privacy_agreed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="필수 약관 및 개인정보처리방침에 동의해야 합니다.",
            )

        # 3. 비밀번호 해싱
        hashed_password = self._hash_password(body.password)

        # 4. 데이터베이스(Supabase)에 저장할 User 모델 객체 생성
        new_user = User(
            email=body.email,
            password=hashed_password,
            terms_agreed=body.terms_agreed,
            privacy_agreed=body.privacy_agreed,
            marketing_agreed=body.marketing_agreed,
        )

        # 5. DB에 추가하고 변경사항 커밋(반영)
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)  # DB에 저장되면서 자동 생성된 ID 등을 객체에 갱신

        return {
            "message": "회원가입이 완료되었습니다.",
            "email": new_user.email,
            "status": status.HTTP_201_CREATED,
        }

    # 로그인 API를 구현할 때 Access Token(액세스 토큰)과 Refresh Token(리프레시 토큰)의 개념과 필요성을 명확히 이해는 것은 안전한 웹 서비스 개발의 핵심입니다.

    # 1. Access Token(액세스 토큰)이란 무엇이며 왜 필요한가요?
    # Access Token은 사용자가 로그인에 성공했을 때 서버가 발급해 주는 "디지털 입장권(신분증)"입니다.
    # 사용자는 이 토큰을 가지고 서버에 요청을 보내면, 서버는 토큰을 확인하여 사용자가 누구인지 인증하고, 해당 사용자가 접근할 수 있는 자원(데이터)에 대한 권한을 부여합니다.
    # 내부에 유저의 식별 정보(예: 이메일, 권한 등)와 만료 시간이 담겨 있으며, 보통 위조를 막기 위해 JWT(JSON Web Token) 형태로 발급됩니다.

    # - 왜 필요할까요?
    # Stateless(무상태) 서버 유지: HTTP 통신은 기본적으로 로그인 상태를 기억하지 못합니다(이전 요청이 누구였는지 모름).
    # 매번 요청할 때마다 아이디/비밀번호를 보내는 것은 보안상 미친 짓이므로,
    # 대신 이 입장권(Access Token)을 헤더(Authorization: Bearer <토큰>)에 실어 보내 "나 로그인한 누구누구야!" 하고 서버에 증명하기 위해 필요합니다.

    # - Access Token의 치명적인 단점 (수명 고민)
    # 이 입장권만 들고 있으면 서버는 누구든 통과시켜 줍니다. 만약 해커가 이 토큰을 가로채면(탈취당하면),
    # 토큰이 만료될 때까지 해커가 그 유저인 것처럼 웹사이트를 마음대로 휘젓고 다닐 수 있습니다.
    # 그래서 수명을 아주 짧게(예: 15분 ~ 30분) 설정해야 안전합니다.

    # 문제점: 수명을 30분으로 짧게 해두면, 사용자가 웹사이트를 이용하다가 30분이 지났을 때
    # 갑자기 로그아웃되어버려서 "로그인을 30분마다 다시 해야 하는 극심한 불편함"이 생깁니다.

    # 2. Refresh Token(리프레시 토큰)은 왜 필요할까요?
    # Access Token이 짧은 수명 때문에 자주 만료되는 문제를 해결하기 위해 만든 "입장권 재발급 쿠폰(열쇠)"입니다.
    # Access Token보다 수명을 훨씬 길게(예: 7일 ~ 14일) 설정합니다.

    # - 왜 필요할까요?
    # 사용자가 로그인을 딱 한 번 하면, Access Token(30분짜리)과 Refresh Token(7일짜리)을 같이 발급받습니다.
    # 30분이 지나 Access Token이 만료되어 API 요청이 거절당했을 때, 프론트엔드(클라이언트)는 사용자에게 "로그인 만료되었으니 다시 아이디/비번 치세요"라고 창을 띄우지 않습니다.
    # 대신, 숨겨두었던 Refresh Token을 서버에 조용히 보내서 "나 아직 로그인 상태 유지 중이니까 Access Token 하나만 새로 발급해 줘!" 하고 요청합니다.
    # 서버는 Refresh Token이 유효한지 확인한 뒤, 새로운 Access Token을 뚝딱 만들어 건네줍니다.
    # 결과: 사용자는 며칠 동안 로그아웃되는 불편함 없이 편리하게 서비스를 이용하면서도, 보안의 핵심인 Access Token의 수명은 짧게 유지할 수 있는 마법 같은 타협점이 완성됩니다.
    def sign_in(self, body: UserLogin):
        # 로그인 로직 구현
        # 예: 사용자 인증 정보를 검증하고, 토큰을 발급하는 동의 작업 수행

        # 1. 이메일 및 비밀번호 검증
        user = self.db.query(User).filter(User.email == body.email).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            )

        # 2. 비밀번호 검증
        if not bcrypt.checkpw(
            body.password.encode("utf-8")[:BCRYPT_MAX_PASSWORD_BYTES],
            user.password.encode("utf-8"),
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            )

        # 3. Access Token 생성 (수명 짦음: 30분) -> API 요청용 입장권
        access_token_expires = timedelta(minutes=30)
        access_token = self._create_token(
            data={"sub": user.email}, expires_delta=access_token_expires
        )

        # 5. 인증 성공 시 토큰 발급
        # 실제 구현에서는 JWT 토큰 등을 발급하여 클라이언트에 반환하는 로직을 추가해야 합니다.
        return {
            "message": "로그인을 성공하였습니다.",
            "access_token": access_token,
            "token_type": "bearer",
        }
