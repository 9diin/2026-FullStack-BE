# 사업 아이디어 도출 API

## 로컬 실행

1. 실제 비밀값은 Git에 커밋되지 않는 `.env.local`에 설정합니다. Gemini API 키는 `GEMINI_API_KEY`에 입력하세요.
   `env/development.env`는 공유 가능한 기본값만 보관합니다.
2. `uv sync` 후 `uv run fastapi dev main.py`로 서버를 실행합니다.
3. `/docs`에서 로그인 후 받은 Bearer access token을 사용해 API를 호출합니다.

`DATABASE_URL`은 Supabase PostgreSQL 연결 주소입니다. 앱 시작 시 SQLAlchemy 모델에 정의된
`idea_source_files`, `idea_generations`, `idea_suggestions`, `idea_selection_events` 테이블이 기존 방식에 따라 생성됩니다.
실서비스에서는 자동 DDL 대신 마이그레이션 적용을 권장합니다.

해결방안 연동을 위해 기존 `idea_elaborations` 테이블에도 `solution` JSONB 컬럼이 필요합니다.
앱 시작 시 PostgreSQL의 기존 테이블에 해당 컬럼이 없으면 자동으로 추가합니다.
수동 배포가 필요하거나 자동 DDL 권한이 없는 환경에서는 다음 DDL을 적용하세요.

```sql
ALTER TABLE idea_elaborations
ADD COLUMN IF NOT EXISTS solution JSONB;
```

## API

- `POST /api/v1/source-files`: 인증된 사용자의 UTF-8 TXT 파일 업로드 (현재 20 MiB까지)
- `POST /api/v1/idea-generations`: 프롬프트와 선택 파일로 구조화된 아이디어 3개 생성
- `POST /api/v1/idea-generations/{generation_id}/selection`: 생성 결과 중 사용자가 선택한 아이디어 기록
- `POST`, `GET /api/v1/idea-generations/{generation_id}/elaboration`: 같은 구체화 응답에 문제인식과 해결방안을 저장·조회. 해결방안의 단계 및 TO-BE 항목은 응답의 페인포인트 ID를 참조합니다.

`project_id`는 아직 프로젝트 소유권 모델이 없어 `null` 또는 생략만 허용합니다.
PDF/DOCX/XLSX 추출도 아직 지원하지 않으며 현재는 UTF-8 TXT만 업로드할 수 있습니다.

생성 입력 원문, LLM이 분류한 관심 분야, 제안 내용은 사용자 ID와 함께 Supabase에 저장됩니다.
선택 API는 변경 전 선택 이벤트도 이력으로 남기고 현재 선택값을 유지합니다. 집계용 분야 분류는
`InterestCategory`의 고정 목록을 사용합니다. 프롬프트와 문서 내용은 민감할 수 있으므로
보존·삭제 정책을 운영에 반영하고, 개인정보 고지 및 LLM 공급자 정책을 확인해야 합니다.

분야별 도출량과 선택 추이는 Supabase SQL Editor에서 다음 형태로 집계할 수 있습니다.

```sql
SELECT category, COUNT(DISTINCT generation_id) AS generation_count,
       COUNT(selection_id) AS selection_count
FROM (
    SELECT g.id AS generation_id, c.category, e.id AS selection_id
    FROM idea_generations AS g
    CROSS JOIN LATERAL json_array_elements_text(g.interest_categories) AS c(category)
    LEFT JOIN idea_selection_events AS e ON e.generation_id = g.id
) AS trend
GROUP BY category
ORDER BY generation_count DESC;
```

Gemini 키가 설정되지 않은 상태에서 API 서버는 실행되지만 생성 요청은 `LLM_UNAVAILABLE` 오류로
응답합니다. 기본 모델과 대체 모델은 `gemini-3.8-flash`이며, 생성 요청은 Gemini Interactions
API를 사용합니다. 모델이 HTTP 400/404를 반환하면 대체 모델을 시도하고, 모든 모델의 요청 할당량을 초과하면
`LLM_QUOTA_EXCEEDED`(429)를 반환합니다. 할당량 초과 시 Google AI Studio에서 사용량·결제
설정을 확인하세요. 실제 모델을 쓰지 않는 테스트는 generator 의존성을 mock으로 대체할 수 있습니다.
