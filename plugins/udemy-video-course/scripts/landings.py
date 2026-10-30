"""`index.html` から各フレームの「着地点」を計算し、`snapshot --at` に渡す文字列を出す。

    python landings.py videos/<unit>

    着地 = min(自分の終わり, 次のフレームの start) − 0.15

★ 他のユニットの時刻を持ち越さない（尺の外を撮って fill/density が 100% 超になった）。
★ `transition` が入るフレームは次の start が自分の終わりより前にあるので、
  単純な start + duration だと crossfade の最中を撮ってしまう。
★ `snapshot --at` は**カンマ区切り**。`--at` の繰り返しは最後の1つしか効かない。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import course_config  # noqa: E402

COURSE = course_config.load()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    unit = COURSE.unit(argv[1])
    idx = unit / "index.html"
    if not idx.exists():
        print("FAIL: %s がありません（先に assemble-index）" % idx)
        return 1
    s = idx.read_text(encoding="utf-8")
    rows = []
    for m in re.finditer(r"<div\b[^>]*>", s):
        t = m.group(0)
        if "data-composition-src" in t and "data-start" in t:
            src = re.search(r"frames/([^\"]+)", t).group(1)
            st = float(re.search(r'data-start="([\d.]+)"', t).group(1))
            du = float(re.search(r'data-duration="([\d.]+)"', t).group(1))
            rows.append((src, st, du))
    rows.sort(key=lambda r: r[1])
    ats = []
    for i, (src, st, du) in enumerate(rows):
        nxt = rows[i + 1][1] if i + 1 < len(rows) else st + du
        ats.append(round(min(st + du, nxt) - 0.15, 2))
        print("  %-28s start %7.3f  dur %6.3f  着地 %7.2f" % (src, st, du, ats[-1]))
    print("総尺 %.3f" % (rows[-1][1] + rows[-1][2]))
    print("AT=" + ",".join(str(a) for a in ats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
