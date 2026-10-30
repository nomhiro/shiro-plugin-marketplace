"""SCRIPT.md の字下げ行（音声になる行）を、Line 番号で差し替える（2026-10-18 新設）。

    python set_lines.py videos/<slug> <lines.json>

lines.json は {"2": "新しい語り", "10": "…"}。見出し `## Line N — …` の直後の字下げ行（半角スペース4つ）を1行だけ置き換える。
差し替えた行番号と、前後の字数を出す。音声を作ったあとに使うときは、その行を `tts.py --only N` で作り直す。
"""
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def main(argv):
    unit, js = Path(argv[1]), Path(argv[2])
    p = unit / "SCRIPT.md"
    lines = p.read_text(encoding="utf-8").splitlines()
    new = {int(k): v.strip() for k, v in json.loads(js.read_text(encoding="utf-8")).items()}
    cur = None
    done = set()
    for i, ln in enumerate(lines):
        m = re.match(r"## Line (\d+) ", ln)
        if m:
            cur = int(m.group(1))
            continue
        if cur in new and ln.startswith("    ") and cur not in done:
            print(f"Line {cur}: {len(ln) - 4} → {len(new[cur])}字")
            lines[i] = "    " + new[cur]
            done.add(cur)
    miss = set(new) - done
    if miss:
        raise SystemExit(f"見つからない Line: {sorted(miss)}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    total = sum(len(l) - 4 for l in lines if l.startswith("    "))
    print(f"OK {p}（字下げ行の合計 {total}字）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
