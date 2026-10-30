"""語末の実測表（_beats.md）を、フレームごとの1行にして見やすくする。

    python dump_beats.py <unit-slug|videos/<unit>>      # 出力: <unit>/.hyperframes/beats.txt（ユニットごと。並列で衝突しない）

`slides.py` の E(frame, "語") に渡す綴りは、ここに出る STT の語を連結したもの（例: 政界ラベル＝正解ラベル）。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import course_config  # noqa: E402

COURSE = course_config.load()
u = COURSE.unit(sys.argv[1])
fence = "`" * 3
t = (u / ".hyperframes" / "frame-packets" / "_beats.md").read_text(encoding="utf-8")
out = []
for m in re.finditer(r"## Frame (\d+) — ([\d.]+)s.*?" + fence + r"\n(.*?)" + fence, t, re.S):
    toks = []
    for line in m.group(3).splitlines():
        x = re.match(r"\s*([\d.]+)s 〜\s*([\d.]+)s\s+(.*)", line)
        if x:
            toks.append(f"{x.group(3)}@{x.group(2)}")
    out.append(f"F{m.group(1)} D={m.group(2)}: " + " ".join(toks))
dst = u / ".hyperframes" / "beats.txt"
dst.write_text("\n".join(out), encoding="utf-8", newline="\n")
print(f"OK: {dst}（{len(out)} フレーム）")
