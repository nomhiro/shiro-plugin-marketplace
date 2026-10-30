"""SCRIPT.md の `## Line N` の字下げ行（語り）を、JSON で渡した文に置き換える。

    python set_script_lines.py videos/<unit>/SCRIPT.md <lines.json>    # lines.json = {"2": "新しい語り", ...}

2026-10-19 新設（L3-1・L4-6 のレビュー反映で、行ごとの置き換えを繰り返したため）。見出し・Delivery・設計メモは触らない。
"""
import json
import re
import sys
from pathlib import Path

p = Path(sys.argv[1])
t = p.read_text(encoding="utf-8")
new = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
for n, text in new.items():
    pat = re.compile(rf"(## Line {n} —[^\n]*\n(?:(?!## )[^\n]*\n)*?)    [^\n]+\n")
    t2, k = pat.subn(lambda m: m.group(1) + "    " + text + "\n", t, count=1)
    if k != 1:
        raise SystemExit(f"Line {n} が見つからない")
    t = t2
p.write_text(t, encoding="utf-8")
print("ok", list(new))
