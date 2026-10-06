from fastapi import FastAPI  # noqa: I001
from fastapi.middleware.cors import CORSMiddleware
from api import api_router

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


# 서버 헬스체크용 루트 앤드포인트
@app.get("/")
def main():
    return {"FASTAPI 서버를 실행하였습니다."}
