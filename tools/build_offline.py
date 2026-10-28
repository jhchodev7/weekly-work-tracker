"""샘플 데이터를 규칙 엔진으로 분석해 frontend/index.html 의 OFFLINE_DATA 에 넣는다.
서버 없이 index.html 을 더블클릭해 열어도 데모가 동작하게 하기 위함.

실행: python tools/build_offline.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import server  # noqa: E402

result = server.analyze_with_rules(server.normalize(server.SAMPLE_TASKS))
result["engine"] = "오프라인 데모 데이터"

html_path = ROOT / "frontend" / "index.html"
html = html_path.read_text(encoding="utf-8")
html = re.sub(r"/\*__OFFLINE__\*/.*?/\*__END__\*/",
              lambda _: "/*__OFFLINE__*/" + json.dumps(result, ensure_ascii=False) + "/*__END__*/",
              html, flags=re.S)
html_path.write_text(html, encoding="utf-8")
print(f"OFFLINE_DATA 갱신 완료 (업무 {len(result['tasks'])}건)")
