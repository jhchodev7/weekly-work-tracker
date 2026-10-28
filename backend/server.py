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

DAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
WEEKDAYS = DAYS[:5]
HOLIDAYS = DAYS[5:]

DEPTS = ["감사", "안전", "ICT", "경영지원", "발전", "전기", "기계"]

SAMPLE_TASKS = [
    {"부서": "경영지원", "업무": "주간 경영회의", "날짜": "월요일", "시간": "10:00-11:00"},
    {"부서": "발전", "업무": "주간 운전 계획 회의", "날짜": "월요일", "시간": "14:00-15:00"},
    {"부서": "기계", "업무": "터빈 윤활유 성분 분석", "날짜": "화요일", "시간": "09:00-12:00"},
    {"부서": "안전", "업무": "전 직원 산업안전 교육", "날짜": "화요일", "시간": "13:00-15:00"},
    {"부서": "ICT", "업무": "전산망 서버 점검", "날짜": "수요일", "시간": "09:00-13:00"},
    {"부서": "감사", "업무": "외부감사 현장실사", "날짜": "수요일", "시간": "10:00-12:00"},
    {"부서": "ICT", "업무": "보안 패치 검토 회의", "날짜": "수요일", "시간": "14:00-15:00"},
    {"부서": "발전", "업무": "운전원 교대 인수인계", "날짜": "목요일", "시간": "09:00-10:00"},
    {"부서": "안전", "업무": "소방 합동훈련", "날짜": "목요일", "시간": "10:00-12:00"},
    {"부서": "안전", "업무": "작업 전 안전 브리핑", "날짜": "목요일", "시간": "13:00-14:00"},
    {"부서": "전기", "업무": "변전소 차단기 교체(정전 작업)", "날짜": "목요일", "시간": "13:00-17:00"},
    {"부서": "발전", "업무": "2호기 발전기 출력 시험", "날짜": "목요일", "시간": "14:00-17:00"},
    {"부서": "전기", "업무": "154kV 송전선로 절체", "날짜": "목요일", "시간": "22:00-04:00"},
    {"부서": "발전", "업무": "3호기 야간 기동 운전", "날짜": "목요일", "시간": "23:00-03:00"},
    {"부서": "기계", "업무": "보일러 급수펌프 정비", "날짜": "금요일", "시간": "09:00-12:00"},
    {"부서": "ICT", "업무": "ERP 시스템 업데이트", "날짜": "금요일", "시간": "13:00-17:00"},
    {"부서": "경영지원", "업무": "월말 결산 전표 마감", "날짜": "금요일", "시간": "14:00-17:00"},
    {"부서": "ICT", "업무": "백업 서버 교체 작업", "날짜": "토요일", "시간": "10:00-16:00"},
    {"부서": "안전", "업무": "휴일 설비 특별 순찰", "날짜": "일요일", "시간": "09:00-12:00"},
]

# ---------------------------------------------------------------------------
# LLM 프롬프트
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """너는 전사 일정 조율 AI야. 배열 형태로 입력된 부서별 주간업무 데이터를 분석해서 \
프론트엔드 레이더 맵이 읽을 수 있는 JSON으로 반환해.

회사는 24시간 운영되는 발전소이고 부서는 감사, 안전, ICT, 경영지원, 발전, 전기, 기계다.
업무는 월요일~일요일에 걸쳐 있고 토요일·일요일은 휴일이다.
시간이 "22:00-06:00"처럼 종료가 시작보다 이르면 자정을 넘겨 다음 날 아침까지 이어지는 야간 작업이다.
"구분" 필드에 야간/휴일 여부가 들어 있다.

분석 기준:
- 시간이 실제로 겹치고(자정을 넘는 야간 작업이 다음 날 새벽 업무와 겹치는 경우 포함), 한쪽이 설비·시스템을 멈추거나
  불안정하게 만드는 작업(서버 점검, 시스템 업데이트, 정전·절체 작업, 설비 교체·정비 등)이고 다른 쪽이 그 설비·시스템에
  의존하는 작업(감사 자료 조회, 발전기 시험·기동, 결산 마감, 비상 훈련 등)이면 충돌이다.
  정전·설비 작업과 발전 운전이 겹치는 경우는 안전사고 위험이므로 특히 엄격히 봐.
- 야간(22~06시)·휴일에는 근무 인력과 감독자가 적다. 이 시간대에 위험작업 두 개가 동시에 진행되면 서로 의존하지 않아도 충돌로 보고,
  야간·휴일이라는 점을 reason 에 밝혀.
- 단순히 같은 날이라는 이유만으로는 충돌로 보지 마. 실제 업무상 위험이 있어야 한다.
- 충돌이면 양쪽 업무 모두 isConflict: true 로 설정하고, conflictWith 에 상대 업무 id 를 넣어.
- reason 은 "서버 점검과 이벤트 발송 겹침"처럼 한 줄 제목 + 왜 위험한지 1~2문장으로 구체적으로 써.
- suggestedDay 는 원칙적으로 월요일~금요일 중 하나. 옮기기 쉬운 쪽(외부 일정·법정 기한에 묶이지 않은 쪽)을 옮기고,
  옮긴 날에 새로운 충돌이 생기지 않도록 다른 업무들을 확인해. 업무는 같은 시간대로 옮겨지므로,
  야간·휴일에만 할 수 있는 작업(정전·절체, 발전기 기동 등)이 아니라면 suggestion 에 평일 주간으로 시간까지 바꾸는 방안도 제시해.
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
    """'10:00-16:00' -> (10, 16). 자정을 넘으면 end 에 24를 더한다: '22:00-06:00' -> (22, 30).
    없으면 업무시간 전체."""
    try:
        start, end = (int(part.split(":")[0]) for part in text.split("-"))
    except (AttributeError, ValueError):
        return 9, 18
    return start, end + 24 if end <= start else end


def fmt_time(t):
    end = f"{t['end'] - 24:02d}:00(익일)" if t["end"] > 24 else f"{t['end']:02d}:00"
    return f"{t['start']:02d}:00-{end}"


def is_night(t):
    return t["start"] < 6 or t["end"] > 22


def off_hours(t):
    """'야간', '휴일', '야간·휴일' 또는 ''."""
    return "·".join(k for k, on in (("야간", is_night(t)), ("휴일", t["day"] in HOLIDAYS)) if on)


def abs_range(t):
    """월요일 00시를 0으로 하는 주 단위 시간 구간."""
    base = DAYS.index(t["day"]) * 24
    return base + t["start"], base + t["end"]


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
         "시간": fmt_time(t), "구분": off_hours(t) or "주간"}
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

RISKY = ["점검", "업데이트", "정전", "절체", "교체", "정비", "마이그레이션", "배포"]
EXPOSED = ["실사", "시험", "마감", "훈련", "감사", "운전", "결산", "교육"]


def has(words, title):
    return any(w in title for w in words)


def overlap(a, b):
    """겹치는 주 단위 시간 구간 (없으면 None). 자정을 넘는 야간 작업도 처리된다."""
    (a0, a1), (b0, b1) = abs_range(a), abs_range(b)
    s, e = max(a0, b0), min(a1, b1)
    return (s, e) if s < e else None


def fmt_overlap(s, e):
    day = DAYS[s // 24 % 7]
    end = f"익일 {e % 24 or 24}시" if (e - 1) // 24 > s // 24 else f"{e - s // 24 * 24}시"
    return f"{day} {s % 24}시~{end}"


def analyze_with_rules(tasks):
    for t in tasks:
        t.update(isConflict=False, conflictWith=[], severity="none",
                 reason="", suggestedDay=t["day"], suggestion="")

    for i, a in enumerate(tasks):
        for b in tasks[i + 1:]:
            span = overlap(a, b)
            if a["dept"] == b["dept"] or not span:
                continue
            s, e = span
            off = off_hours({"day": DAYS[s // 24 % 7], "start": s % 24, "end": s % 24 + e - s})
            when = fmt_overlap(*span) + (f"({off})" if off else "")
            if has(RISKY, a["title"]) and has(EXPOSED, b["title"]):
                risky, exposed = a, b
            elif has(RISKY, b["title"]) and has(EXPOSED, a["title"]):
                risky, exposed = b, a
            elif off and has(RISKY, a["title"]) and has(RISKY, b["title"]):
                risky, exposed = sorted((a, b), key=lambda t: t["end"] - t["start"], reverse=True)
            else:
                continue

            new_day = pick_free_day(tasks, exposed)
            if has(EXPOSED, exposed["title"]):
                reason = (f"{risky['title']}과(와) {exposed['title']} 겹침 — {when}에 "
                          f"{risky['dept']}팀 작업으로 설비·시스템이 중단된 상태에서 {exposed['dept']}팀 "
                          f"업무가 진행되어 업무 중단 및 안전사고 위험이 있습니다.")
            else:
                reason = (f"{off} 위험작업 동시 진행 — {when}에 {risky['dept']}팀 '{risky['title']}'과(와) "
                          f"{exposed['dept']}팀 '{exposed['title']}'이(가) 동시에 진행됩니다. "
                          f"근무 인력과 감독자가 적은 시간대라 사고 시 대응이 늦어질 위험이 있습니다.")
            suggestion = (f"'{exposed['title']}'을(를) {new_day} 같은 시간대로 옮기는 것을 제안합니다. "
                          f"{new_day}은(는) 설비·시스템 작업이 없어 안정적이고 전사 업무 밀도가 낮습니다.")
            if off and not has(["정전", "절체", "기동"], exposed["title"]):
                suggestion += " 야간·휴일에 꼭 해야 하는 작업이 아니라면 평일 주간으로 시간을 옮기는 것이 더 안전합니다."
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

    candidates = [d for d in WEEKDAYS if d != moving["day"]]
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
