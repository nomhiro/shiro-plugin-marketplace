"""新しい型の STORYBOARD.md を作る（front matter は旧版から残し、本文はフレームの器だけ）。
scene・voiceover・transition_in は slides.py の render_pages が、duration は sync-durations が埋める。

    python new_storyboard.py <unit-slug> <id1> <id2> ...      # id はフレーム番号順（例: 01-position 02-hook ...）

無音の「考える時間」フレームの duration は、作った後に STORYBOARD の該当ブロックを 6s に手で直す（sync-durations は音声の無いフレームを触らない）。
"""
import sys
from pathlib import Path

unit, ids = sys.argv[1], sys.argv[2:]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import course_config  # noqa: E402

d = course_config.load().unit(unit)
old = (d / "STORYBOARD.md").read_text(encoding="utf-8")
fm = old[: old.index("---", 3) + 3]
out = [fm, "\n\n> **1ユニット＝1レクチャーの型（プラグインの `references/slide-format.md` §2d）。** scene・voiceover・transition_in は `slides.py`（render_pages）が合わせる。\n"
       "> **フレーム番号は音声の wav 番号**（1〜N の連番）。\n"]
for n, fid in enumerate(ids, 1):
    out.append(f"\n## Frame {n} — (slides.py が付ける)\n\n- scene: -\n- voiceover: \"\"\n- duration: 5s\n"
               f"- transition_in: {'cut' if n == 1 else 'crossfade 0.5s'}\n- status: built\n"
               f"- src: compositions/frames/{fid}.html\n- type: {'hook' if n == 1 else 'explain'}\n")
(d / "STORYBOARD.md").write_text("".join(out), encoding="utf-8", newline="\n")
print(unit, len(ids), "frames")
