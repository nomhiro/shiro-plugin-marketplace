# -*- coding: utf-8 -*-
"""裏の処理（render_units.py・make_lecture.py）が止められたあと、何が済んで何が残っているかを1回で見る（読み取り専用）。

    python render_status.py <lecture-id> <unit> [<unit> ...]
    例: python render_status.py L5-2 lecture-5-2-open cli-scripts-handson lecture-5-2-close

なぜ要るか: 処理が止められたあと、2回続けて「3本とも未レンダリング」と誤って報告した（実際は3本とも済み）。
報告の前に必ずこれを流す。

各ユニット: video.mp4 の有無・時刻・尺と、組み直し（compositions/frames の最新）より新しいか／字幕の有無／ログの最後の行。
最後に、連結（<lectures_out_dir>/<lecture-id>/lecture.mp4）の有無と尺。
"""
from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import course_config  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def duration(p: Path) -> str:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    return r.stdout.strip() or "?"


def hm(p: Path) -> str:
    return datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%H:%M")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    course = course_config.load()
    lec, units = argv[1], argv[2:]
    for u in units:
        d = course.unit(u)
        v = d / "renders" / "video.mp4"
        frames = sorted((d / "compositions" / "frames").glob("*.html"), key=lambda p: p.stat().st_mtime)
        if v.is_file():
            fresh = not frames or v.stat().st_mtime > frames[-1].stat().st_mtime
            st = "済（組み直しより新しい）" if fresh else "古い（組み直しより前）"
            print(f"{d.name}: video.mp4 {hm(v)} {duration(v)}秒 {st}")
        else:
            print(f"{d.name}: video.mp4 なし")
        srt = d / "subtitles.ja.srt"
        print("  字幕: 済" if srt.is_file() and v.is_file() and srt.stat().st_mtime > v.stat().st_mtime else "  字幕: 未")
        log = d / "renders" / "render.log"
        if log.is_file():
            lines = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            if lines:
                print(f"  ログ: {lines[-1]}")
    lecture = course.path("lectures_out_dir") / lec / "lecture.mp4"
    print(f"連結: {lecture} {hm(lecture)} {duration(lecture)}秒" if lecture.is_file() else "連結: 未")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
