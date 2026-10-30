"""index.html から各フレームの 開始直後(+0.7s)・途中(中間)・着地(次の開始 − 0.15) を出す。"""
import re
import sys
from pathlib import Path

html = (Path(sys.argv[1]) / "index.html").read_text(encoding="utf-8")
fr = [(m.group(1), float(m.group(2)), float(m.group(3)))
      for m in re.finditer(r'data-composition-src="compositions/frames/([^"]+)\.html"\s+data-start="([\d.]+)"\s+data-duration="([\d.]+)"', html)]
fr.sort(key=lambda t: t[1])
out = []
for i, (fid, st, du) in enumerate(fr):
    end = st + du
    nxt = fr[i + 1][1] if i + 1 < len(fr) else end
    land = min(end, nxt) - 0.15
    out += [round(st + 0.7, 2), round((st + 0.7 + land) / 2, 2), round(land, 2)]
print(",".join(f"{t:g}" for t in out))
