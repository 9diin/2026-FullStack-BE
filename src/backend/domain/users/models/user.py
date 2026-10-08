from datetime import UTC, datetime

# uv add sqlalchemy 명령어로 설치된 SQLAlchemy를 사용하기 위해 필요한 모듈을 임포트합니다.
from sqlalchemy import Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base

# [요구사항]
# - user_id: uuid로 만들기
# - 테이블 조인 시, 활용 방안 강구


# Users 테이블 ORM 모델 정의
# 데이터베이스의 'users' 테이블과 매핑되는 SQLAlchemy ORM 모델을 정의합니다.
# Base: SQLAlchemy의 ORM 모델을 정의하기 위한 기본 클래스입니다. 이 클래스를 상속받아 User 모델을 정의합니다.
class User(Base):
    __tablename__ = "users"  # 데이터베이스 테이블 이름

    # SQLAlchemy ORM 모델의 컬럼 정의
    # * Mapped[...]: "이 변수는 데이터베이스 테이블의 컬럼과 매핑될 파이썬 속성입니다"라고 SQLAlchemy에게 알려주는 타입 힌트입니다.
    #                파이썬의 표준 타입 힌트 시스템과 연동되어, IDE(예: PyCharm, VSCode)에서 자동 완성 및 타입 검사를 지원합니다.
    # * [str], [int], [bool], [datetime] 등은 컬럼의 데이터 타입을 나타냅니다.
    #   파이썬 코드 안에서 이 데이터가 다뤄질 자료형을 지정합니다.
    #   데이터베이스에서 데이터를 꺼내왔을 때, 파이썬이 이를 문자열(str), 정수(int), 불리언(bool), 날짜/시간(datetime) 객체로 안전하게 인식하고 처리할 수 있게 만들어 줍니다.
    # * mapped_column(...): SQLAlchemy ORM 모델의 컬럼을 정의하는 함수입니다.
    #   데이터베이스 테이블에서 실제로 생성될 컬럼의 제약 조건과 옵션(SQL 규칙)을 정의하는 함수입니다.
    #   "이 컬럼은 비어 있으면 안 돼(nullable=False), 고유해야 돼(unique=True), 기본값이 있어야 돼(default=...), 자동 증가해야 돼(autoincrement=True)" 등과 같은 제약 조건을 설정할 수 있습니다.

    # 1. 회원 고유 ID (Primary Key)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 2. 사용자 이메일 주소 (Unique)
    email: Mapped[str] = mapped_column(unique=True, nullable=False)

    # 3. 사용자 비밀번호 (Hashed)
    password: Mapped[str] = mapped_column(nullable=False)

    # 4. 약관 동의 여부 - 서비스 이용약관, 개인정보 처리방침, 마케팅 광고 수신 동의
    # Boolean: 데이터베이스에 TRUE 또는 FALSE 값으로 저장되도록 지정합니다.
    terms_agreed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    privacy_agreed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    marketing_agreed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # 5. 생성 및 수정 타임스탬프 (타임존을 포함한 표준 UTC 적용)
    # * 일반 값 전달 (서버가 켜질 때의 고정된 시간 '하나'만 계속 사용됨)
    #   default = datetime.now(UTC)

    # * 람다 전달 (데이터가 DB에 꽂힐 때마다 함수가 실행되어 '새로운 현재 시간'을 가져옴)
    #   default = lambda: datetime.now(UTC)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
