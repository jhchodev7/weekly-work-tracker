# WORKSYNC — 주간업무 현황판

부서(감사·안전·ICT·경영지원·발전·전기·기계)별 주간업무(야간·휴일 작업 포함)를 AI가 분석해 일정 충돌을 주간 일정표와 히트맵으로 보여주는 대시보드.

## 실행

```bash
pip install -r requirements.txt     # Claude 분석을 쓸 때만 필요
set ANTHROPIC_API_KEY=sk-ant-...     # PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
python backend/server.py
```

브라우저에서 http://localhost:8000 접속.

- API 키나 `anthropic` 패키지가 없으면 자동으로 **로컬 규칙 엔진**으로 분석합니다.
- 서버 없이 `frontend/index.html`을 바로 열어도 오프라인 데모 데이터로 동작합니다.
  샘플 데이터를 바꿨다면 `python tools/build_offline.py`로 갱신하세요.

## 구조

| 파일 | 내용 |
|---|---|
| `backend/server.py` | HTTP 서버, LLM 프롬프트(`SYSTEM_PROMPT`), JSON 스키마, 규칙 엔진, 샘플 데이터 |
| `frontend/index.html` | React 18 + Tailwind (CDN, 빌드 불필요): 리스크 타임라인, 상세 주간 일정표, 히트맵, 충돌 모달 |
| `tools/build_offline.py` | 오프라인 데모 데이터 생성 |
| `DEMO.md` | 해커톤 발표 시연 시나리오 |

## API

`POST /api/analyze`

```json
[{"부서": "ICT", "업무": "전산망 서버 점검", "날짜": "수요일", "시간": "09:00-13:00"},
 {"부서": "전기", "업무": "송전선로 절체", "날짜": "목요일", "시간": "22:00-04:00"}]
```

- `날짜`: 월요일~일요일 (토·일은 휴일)
- `시간`: 종료가 시작보다 이르면 자정을 넘는 야간 작업 (`22:00-04:00` = 목 22시 ~ 금 04시)

응답의 `tasks[]`에는 `isConflict`, `conflictWith`, `severity`, `reason`, `suggestedDay`, `suggestion`이 들어갑니다.
Claude 호출은 `claude-opus-5-5` + JSON Schema 구조화 출력을 쓰고, 안전 분류기 거절 시 서버 측 fallback(`fallbacks: "default"`)이 켜져 있습니다.
