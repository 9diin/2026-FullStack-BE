from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.core.config import settings


# [1단계] SQLAlchemy 모델 베이스 클래스 정의
# 모든 ORM 모델(User 등)이 상속받아야 하는 공통 부모 클래스입니다.
class Base(DeclarativeBase):
    pass


# [2단계] 데이터베이스 연결 주소 설정
# 환경 변수 설정 파일(settings)에서 DB 접속 주소(URL)를 가져옵니다.
DATABASE_URL = settings.DATABASE_URL

# [3단계] 데이터베이스 엔진(Engine) 생성
# 실제로 DB 서버와 연결을 맺고 통신을 담당하는 핵심 관리자입니다.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # DB 연결이 끊어졌는지(Timeout 등) 미리 확인하고 자동 재연결합니다. (실무 필수 옵션)  # noqa: E501
    pool_recycle=3600,  # 일정 시간(1시간)이 지난 커넥션은 안전하게 교체(재활용)하여 메모리 누수를 방지합니다.  # noqa: E501
)

# [4단계] 세션 팩토리(Session Local) 생성
# 데이터베이스와 실제로 대화(조회, 저장, 수정 등)할 수 있는 임시 작업 공간(Session)을 찍어내는 공장입니다.  # noqa: E501
SessionLocal = sessionmaker(
    bind=engine,  # 어떤 엔진과 연결될 것인지 지정
    autoflush=False,  # 데이터를 자동으로 미리 반영(Flush)하지 않고 수동으로 제어합니다.
    autocommit=False,  # 작업을 완료(commit)하기 전까지 DB에 영구 반영되지 않도록 안전장치를 켭니다.  # noqa: E501
)


# [5단계] FastAPI 의존성 주입(Dependency Injection)용 제너레이터 함수
# API 요청이 들어올 때마다 데이터베이스 세션을 열어주고, 작업이 끝나면 무조건 닫아줍니다.
def get_db():
    db = SessionLocal()  # 1. 데이터베이스 세션(작업 공간) 열기

    try:
        yield db  # 2. API 라우터 함수에 세션을 전달하여 로직을 수행하도록 함
    finally:
        db.close()  # 3. 에러가 나든 성공하든 상관없이, 요청이 끝나면 세션을 안전하게 닫음 (메모리 릭 방지)  # noqa: E501


# [스토리로 이해하는 DB 연결] Supabase 은행에 민원 처리하러 가기
# 우리가 만드는 파이썬 서버는 회원 정보를 직접 기억할 금고가 없습니다.
# 그래서 클라우드에 있는 Supabase(거대한 은행 금고)에 모든 걸 맡겨야 합니다.
# 이 database.py 파일은 그 은행과 거래하기 위해 세워둔 '우리 회사 안내소'입니다.

# 안내소 안에는 딱 4가지 핵심 도구가 있습니다.

# 1. Base = 표준 건축 설계도 양식
# - 무엇인가요? : 데이터베이스에 테이블(표)을 만들 때 쓰는 기본 도화지입니다.
# - 비유: 아파트를 지을 때 모든 집이 반드시 지켜야 하는 '기본 도면 양식'입니다.
#        앞으로 만들 User 같은 표는 전부 이 양식을 똑같이 복사해서 만듭니다.

# 2. engine = Supabase 금고로 가는 직통 전화선
# 무엇인가요?: 우리 프로그램과 진짜 Supabase 서버를 연결해 주는 물리적인 통로입니다.
# 비유: 우리 사무실 책상에서 Supabase 금고까지 연결된 전용 직통 전화기를 딱 설치해 둔 것입니다.  # noqa: E501
# (참고: pool_pre_ping=True는 전화선이 끊어지지 않았나 중간에 "여보세요?"하고 자꾸 확인해보는 든든한 기능이에요!)  # noqa: E501

# 3. SessionLocal = 은행 창구 직원 자동 발급기
# 무엇인가요?: DB에 접속해서 데이터를 조회하거나 저장해 줄 '일꾼(세션)'을 필요할 때마다 찍어내는 공장입니다.  # noqa: E501
# 비유: 은행에 손님이 올 때마다 업무를 처리해 주는 창구 직원을 무한정 뽑아낼 수 있는 마법의 기계입니다.  # noqa: E501

# 4. get_db() = 직원 대여 및 퇴근 관리 규칙
# 무엇인가요?: 웹 요청이 올 때마다 일꾼(직원)을 잠깐 빌려주고, 일이 끝나면 무조건 칼퇴(해고)시키는 안전 규칙입니다.  # noqa: E501

# 동작 흐름 (3단계):
# 1) db = SessionLocal() ➔ 손님이 회원가입 요청을 하면, "창구 직원 한 명 나와주세요!" 하고 부릅니다.  # noqa: E501
# 2) yield db ➔ 그 직원의 손을 빌려 회원가입 서류를 처리(DB에 저장)합니다.
# 3) finally: db.close() ➔ 일이 성공하든, 중간에 에러가 나서 터지든 상관없이 무조건 직원을 돌려보내고(닫고) 창구를 잠급니다.  # noqa: E501
#    (만약 이걸 안 하면 직원이 퇴근을 못 하고 계속 쌓여서 은행이 마비됩니다 = 메모리 누수 방지)  # noqa: E501
