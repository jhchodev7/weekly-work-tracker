"""전사 일정 레이더 - 백엔드 서버

- GET  /             : frontend/index.html 서빙
- GET  /api/sample   : 샘플 주간업무 데이터
- POST /api/analyze  : 주간업무 배열 -> 충돌 분석 JSON

ANTHROPIC_API_KEY(또는 `ant auth login` 프로필)가 있으면 Claude로 분석하고,
없거나 호출이 실패하면 로컬 규칙 엔진으로 대체한다 (해커톤 데모용 안전장치).

실행: python backend/server.py   ->  http://localhost:8000
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "frontend" / "index.html"
PORT = int(os.environ.get("PORT", "8000"))
MODEL = "claude-opus-5-5"

DAYS = ["월요일", "화요일", "수요일", "목요일", "금요일"]

DEPTS = ["감사", "안전", "ICT", "경영지원", "발전", "전기", "기계"]

SAMPLE_TASKS = [
    {"부서": "경영지원", "업무": "주간 경영회의", "날짜": "월요일", "시간": "10:00-11:00"},
    {"부서": "발전", "업무": "주간 운전 계획 회의", "날짜": "월요일", "시간": "14:00-15:00"},
    {"부서": "기계", "업무": "터빈 윤활유 성분 분석", "날짜": "화요일", "시간": "09:00-12:00"},
    {"부서": "안전", "업무": "전 직원 산업안전 교육", "날짜": "화요일", "시간": "13:00-15:00"},
    {"부서": "ICT", "업무": "전산망 서버 점검", "날짜": "수요일", "시간": "09:00-13:00"},
    {"부서": "감사", "업무": "외부감사 현장실사", "날짜": "수요일", "시간": "10:00-12:00"},
    {"부서": "안전", "업무": "소방 합동훈련", "날짜": "목요일", "시간": "10:00-12:00"},
    {"부서": "전기", "업무": "변전소 차단기 교체(정전 작업)", "날짜": "목요일", "시간": "13:00-17:00"},
    {"부서": "발전", "업무": "2호기 발전기 출력 시험", "날짜": "목요일", "시간": "14:00-17:00"},
    {"부서": "기계", "업무": "보일러 급수펌프 정비", "날짜": "금요일", "시간": "09:00-12:00"},
    {"부서": "ICT", "업무": "ERP 시스템 업데이트", "날짜": "금요일", "시간": "13:00-17:00"},
    {"부서": "경영지원", "업무": "월말 결산 전표 마감", "날짜": "금요일", "시간": "14:00-17:00"},
]

# ---------------------------------------------------------------------------
# LLM 프롬프트
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """너는 전사 일정 조율 AI야. 배열 형태로 입력된 부서별 주간업무 데이터를 분석해서 \
프론트엔드 레이더 맵이 읽을 수 있는 JSON으로 반환해.

회사는 발전소이고 부서는 감사, 안전, ICT, 경영지원, 발전, 전기, 기계다.

분석 기준:
- 같은 요일에 시간이 겹치고, 한쪽이 설비·시스템을 멈추거나 불안정하게 만드는 작업(서버 점검, 시스템 업데이트,
  정전 작업, 설비 교체·정비 등)이고 다른 쪽이 그 설비·시스템에 의존하는 작업(감사 자료 조회, 발전기 시험,
  결산 마감, 비상 훈련 등)이면 충돌이다. 정전·설비 작업과 발전 운전이 겹치는 경우는 안전사고 위험이므로 특히 엄격히 봐.
- 단순히 같은 날이라는 이유만으로는 충돌로 보지 마. 실제 업무상 위험이 있어야 한다.
- 충돌이면 양쪽 업무 모두 isConflict: true 로 설정하고, conflictWith 에 상대 업무 id 를 넣어.
- reason 은 "서버 점검과 이벤트 발송 겹침"처럼 한 줄 제목 + 왜 위험한지 1~2문장으로 구체적으로 써.
- suggestedDay 는 월요일~금요일 중 하나. 옮기기 쉬운 쪽(외부 일정·법정 기한에 묶이지 않은 쪽)을 옮기고,
  옮긴 날에 새로운 충돌이 생기지 않도록 다른 업무들을 확인해.
- suggestion 에는 무엇을 언제로 옮기고 왜 그날이 좋은지, 대안이 있으면 대안까지 2~3문장으로 써.
- severity 는 high(서비스 장애·매출 손실 가능), medium(품질 저하), low(불편) 중 하나.
- 충돌이 아닌 업무는 isConflict: false, conflictWith: [], reason/suggestion 은 빈 문자열, suggestedDay 는 원래 날짜로 둬.
- 입력의 id 순서와 개수를 그대로 유지해.
- summary 에는 이번 주 전체 리스크를 한두 문장으로 요약해."""

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "isConflict": {"type": "boolean"},
                    "conflictWith": {"type": "array", "items": {"type": "string"}},
                    "severity": {"type": "string", "enum": ["high", "medium", "low", "none"]},
                    "reason": {"type": "string"},
                    "suggestedDay": {"type": "string", "enum": DAYS},
                    "suggestion": {"type": "string"},
                },
                "required": ["id", "isConflict", "conflictWith", "severity",
                             "reason", "suggestedDay", "suggestion"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "tasks"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# 입력 정규화
# ---------------------------------------------------------------------------

def parse_hours(text):
    """'10:00-16:00' -> (10, 16). 없으면 업무시간 전체."""
    try:
        start, end = text.split("-")
        return int(start.split(":")[0]), int(end.split(":")[0])
    except (AttributeError, ValueError):
        return 9, 18


def normalize(raw_tasks):
    tasks = []
    for i, t in enumerate(raw_tasks):
        day = t.get("날짜") or t.get("day") or "월요일"
        if day not in DAYS:
            day = next((d for d in DAYS if d.startswith(day[:1])), "월요일")
        start, end = parse_hours(t.get("시간") or t.get("time"))
        tasks.append({
            "id": f"t{i + 1}",
            "dept": t.get("부서") or t.get("dept") or "기타",
            "title": t.get("업무") or t.get("title") or "(제목 없음)",
            "day": day,
            "start": start,
            "end": end,
        })
    return tasks


# ---------------------------------------------------------------------------
# Claude 분석
# ---------------------------------------------------------------------------

def analyze_with_claude(tasks):
    import anthropic

    client = anthropic.Anthropic()
    payload = [
        {"id": t["id"], "부서": t["dept"], "업무": t["title"], "날짜": t["day"],
         "시간": f"{t['start']:02d}:00-{t['end']:02d}:00"}
        for t in tasks
    ]
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": RESULT_SCHEMA},
        },
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"Claude stop_reason={response.stop_reason}")

    text = next(b.text for b in response.content if b.type == "text")
    result = json.loads(text)
    by_id = {r["id"]: r for r in result["tasks"]}
    merged = [{**t, **{k: v for k, v in by_id.get(t["id"], {}).items() if k != "id"}}
              for t in tasks]
    return {"summary": result["summary"], "tasks": merged}


# ---------------------------------------------------------------------------
# 로컬 규칙 엔진 (API 키 없을 때 / 오프라인 데모용)
# ---------------------------------------------------------------------------

RISKY = ["점검", "업데이트", "정전", "교체", "정비", "마이그레이션", "배포"]
EXPOSED = ["실사", "시험", "마감", "훈련", "감사", "운전", "결산", "교육"]


def has(words, title):
    return any(w in title for w in words)


def overlaps(a, b):
    return a["day"] == b["day"] and a["start"] < b["end"] and b["start"] < a["end"]


def analyze_with_rules(tasks):
    for t in tasks:
        t.update(isConflict=False, conflictWith=[], severity="none",
                 reason="", suggestedDay=t["day"], suggestion="")

    for i, a in enumerate(tasks):
        for b in tasks[i + 1:]:
            if a["dept"] == b["dept"] or not overlaps(a, b):
                continue
            pair = None
            if has(RISKY, a["title"]) and has(EXPOSED, b["title"]):
                pair = (a, b)
            elif has(RISKY, b["title"]) and has(EXPOSED, a["title"]):
                pair = (b, a)
            if not pair:
                continue
            risky, exposed = pair
            new_day = pick_free_day(tasks, exposed)
            reason = (f"{risky['title']}과(와) {exposed['title']} 겹침 — "
                      f"{risky['day']} {max(a['start'], b['start'])}시~{min(a['end'], b['end'])}시에 "
                      f"{risky['dept']}팀 작업으로 설비·시스템이 중단된 상태에서 {exposed['dept']}팀 "
                      f"업무가 진행되어 업무 중단 및 안전사고 위험이 있습니다.")
            suggestion = (f"'{exposed['title']}'을(를) {new_day} 같은 시간대로 옮기는 것을 제안합니다. "
                          f"{new_day}은(는) 설비·시스템 작업이 없어 안정적이고 전사 업무 밀도가 낮습니다.")
            for t in (risky, exposed):
                t["isConflict"] = True
                t["conflictWith"].append(exposed["id"] if t is risky else risky["id"])
                t["severity"] = "high"
                t["reason"] = reason
                t["suggestion"] = suggestion
            exposed["suggestedDay"] = new_day

    n = sum(1 for t in tasks if t["isConflict"]) // 2
    summary = (f"이번 주 고위험 일정 충돌 {n}건이 감지되었습니다. 설비·시스템 작업과 이에 의존하는 업무가 "
               f"겹치는 구간을 우선 조정하세요." if n else "이번 주 일정 충돌이 없습니다.")
    return {"summary": summary, "tasks": tasks}


def pick_free_day(tasks, moving):
    # 이미 이동 제안된 업무는 옮겨갈 날짜 기준으로 부하를 계산
    def load(day):
        on_day = [t for t in tasks if t["suggestedDay"] == day]
        if any(has(RISKY, t["title"]) for t in on_day):
            return 99
        return sum(t["end"] - t["start"] for t in on_day)

    candidates = [d for d in DAYS if d != moving["day"]]
    return min(candidates, key=load)


def analyze(raw_tasks):
    tasks = normalize(raw_tasks)
    try:
        result = analyze_with_claude([dict(t) for t in tasks])
        result["engine"] = f"Claude ({MODEL})"
    except Exception as e:  # SDK 미설치, 인증 없음, 네트워크 오류 등
        print(f"[analyze] Claude 사용 불가 -> 규칙 엔진 사용: {e!r}", file=sys.stderr)
        result = analyze_with_rules(tasks)
        result["engine"] = "로컬 규칙 엔진"
    return result


# ---------------------------------------------------------------------------
# HTTP 서버
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/sample":
            self._send(200, SAMPLE_TASKS)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/analyze":
            return self._send(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"null")
            raw = body if isinstance(body, list) else (body or {}).get("tasks", SAMPLE_TASKS)
            self._send(200, analyze(raw))
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid JSON"})


if __name__ == "__main__":
    print(f"Schedule Radar 서버: http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
