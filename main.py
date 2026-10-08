from fastapi import FastAPI  # noqa: I001
from fastapi.middleware.cors import CORSMiddleware


from api import api_router
from backend.core.database import Base, engine

# SQLAlchemy가 User 모델을 인식하도록 임포트해야 합니다.
from backend.domain.users.models.user import User  # noqa: F401


# FastAPI 애플리케이션 초기화
app = FastAPI(
    title="1인 예비창업자/초기창업자를 위한 AI 사업계획서 도출 플랫폼",
    description="",
    version="1.0.0",
)


# [권장] 프런트엔드 연동을 위한 CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,  # 허용할 도메인만 명시 (예: ["http://localhost:3000"])
    allow_methods=["*"],
    allow_headers=["*"],
)

# 도메인 라우터 등록
app.include_router(api_router)

# "자, 우리가 준비한 설계도(Base)를 가지고, Engine을 통해 Supabase로 달려가서
# 아직 테이블이 없으면 당장 지어 올려라!"라고 명령하는 코드입니다.
Base.metadata.create_all(bind=engine)


# 서버 헬스체크용 루트 앤드포인트
@app.get("/")
def main():
    return {"FASTAPI 서버를 실행하였습니다."}


# 서버를 켜면 어떻게 Supabase에 테이블이 생길까?
# 지금까지 만든 database.py와 model.py(User 설계도)는 건축가로 치면 "멋진 아파트 청사진(설계도)"을 종이에 곱게 그려둔 상태입니다.
# 하지만 종이에만 그려두면 뭐 하나요? 땅(Supabase) 위에 실제로 아파트 건물(테이블)을 지어 올려야 사람이 살 수 있겠죠?
# 이 아파트 건물을 Supabase에 짓는 순간은 바로 서버의 메인 파일(main.py)이 켜지는 찰나에 일어납니다.

# 1단계: 메인 파일(main.py)에 시공 명령 내리기
# 서버를 실행하는 대문 파일(main.py)에 다음과 같은 한 줄의 마법 같은 명령어를 적어둡니다.
# Base.metadata.create_all(bind=engine)

# 2단계: 서버 실행(uv run fastapi dev)과 동시에 포클레인 출동!
# 우리가 터미널에 `uv run fastapi dev` 명령어를 입력하는 순간, FastAPI는 main.py를 위에서부터 차례대로 읽기 시작합니다.
#
# 3단계: 설계도(`User`)와 통신선(`engine`) 결합 완료
# main.py 중간에 작성한 `from backend.domain.users.models.user import User` 덕분에
# 파이썬 메모리 공간에는 "어떤 테이블(컬럼, 데이터 타입 등)을 만들어야 하는지"에 대한 정보가 완벽하게 적재됩니다.
#
# 4단계: Supabase 데이터베이스에 테이블 자동 생성 (시공 완료)
# 마지막 줄의 `Base.metadata.create_all(bind=engine)`이 실행되는 순간,
# 파이썬은 설정된 `engine`(Supabase 연결 정보)을 타고 원격 데이터베이스로 접속하여
# 아직 존재하지 않는 테이블(예: `users`)을 찾아내고 즉시 데이터베이스 스키마를 생성합니다.
#
# 결론적으로, 서버를 켤 때마다 DB 구조를 수동으로 일일이 생성할 필요 없이
# ORM 모델 기반으로 안전하게 테이블 세팅이 자동화되는 편리한 구조가 완성됩니다!
