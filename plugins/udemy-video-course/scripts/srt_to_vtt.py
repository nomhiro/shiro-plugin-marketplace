"""SRT 字幕を WebVTT に変換する（Udemy の字幕は WebVTT のみ。SRT は「WEBVTT ヘッダーがありません」で弾かれる）。

    python srt_to_vtt.py <file.srt> [<file.srt> ...]   → 同じ場所に <file>.vtt を書く

- 先頭に `WEBVTT` 行を置き、時刻の小数点（, → .）だけを直す。番号の行と本文はそのまま
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TIME = re.compile(r"(\d{2}:\d{2}:\d{2}),(\d{3})")


def convert(src: Path) -> Path:
    text = src.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    lines = [TIME.sub(r"\1.\2", ln) if "-->" in ln else ln for ln in text.split("\n")]
    out = src.with_suffix(".vtt")
    out.write_text("WEBVTT\n\n" + "\n".join(lines).strip() + "\n", encoding="utf-8", newline="\n")
    return out


def main() -> int:
    for a in sys.argv[1:]:
        print("OK:", convert(Path(a)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
