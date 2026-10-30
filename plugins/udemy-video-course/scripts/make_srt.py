"""台本と音声メタから Udemy 用の字幕（`.srt`）を作る。

## なぜ必要か

この講座は **画面内の文字を図のラベルと要点だけに絞る**方針にした
（ナレーションと同じ文を画面に出すと、読む処理と聞く処理が競合して理解が落ちる）。
その代わり**逐語テキストは字幕で担保する**。字幕が無いとこの方針が成立しない。

## 行単位で十分なので、行ごとの実尺だけで作る

`audio_meta.json` の `voices[].duration_s` に**行ごとの実尺**があるので、
先頭から積み上げれば各行の開始・終了が確定する。行単位の字幕は Udemy で標準的。

語単位のタイムスタンプが必要なとき（図解のビートを台詞に合わせるとき）は
**`word_times.py`** を使う。Speech-to-Text で実測の発話時刻を取る。
字幕には使わない。行単位で読みやすさが足りているため。

## 字幕は「正本」から作る

`SCRIPT.md` の**字下げ行**（＝台詞）から作る。`tts.py` も同じ行を
同じ順で読み上げるので、行の対応は「上から N 行目」で取れば一致する。

## フレーム間の無音も尺に入れる

無音フレーム（`voiceover: ""`）は `audio_meta.json` に現れない。
`STORYBOARD.md` の `duration:` を順に見て、**音声のあるフレームは実尺、
無いフレームはその `duration` を足す**ことで、動画の時間軸と字幕が合う。

## 使い方

    python make_srt.py videos/confusion-matrix-explained
    python make_srt.py videos/confusion-matrix-explained --out subtitles.ja.srt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

FRAME_RE = re.compile(r"^#{2,3}\s+(?:Frame|Beat|Scene)\b.*?(\d+)", re.I)
DURATION_RE = re.compile(r"^\s*[-*]\s+duration\s*:\s*([\d.]+)\s*s", re.I)
# `## Line N — ラベル (Frame N)` から担当フレーム番号を取る
LINE_RE = re.compile(r"^##\s+Line\s+\d+.*?\(Frame\s+(\d+)\)", re.I)
# 字幕の1行に入れる最大文字数。長いと2行に折って読ませる
WRAP = 28


def timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def frame_durations(storyboard: Path) -> dict[int, float]:
    """フレーム番号 → 尺（秒）。STORYBOARD.md の並び順を時間軸とみなす。"""
    out: dict[int, float] = {}
    cur: int | None = None
    for line in storyboard.read_text(encoding="utf-8").splitlines():
        h = FRAME_RE.match(line)
        if h:
            cur = int(h.group(1))
            continue
        if cur is not None:
            m = DURATION_RE.match(line)
            if m and cur not in out:
                out[cur] = float(m.group(1))
    return out


def spoken_by_frame(script: Path) -> dict[int, str]:
    """フレーム番号 → 台詞（漢字のままの正本から取る）。"""
    out: dict[int, str] = {}
    cur: int | None = None
    for line in script.read_text(encoding="utf-8").splitlines():
        h = LINE_RE.match(line)
        if h:
            cur = int(h.group(1))
            continue
        if cur is None:
            continue
        if line.startswith(("    ", "\t")) and line.strip():
            text = line.strip()
            if text.startswith(("**", ">", "#", "|", "-")):
                continue
            out.setdefault(cur, text)
    return out


def wrap(text: str, width: int = WRAP) -> str:
    """句読点を優先して2行に折る。字幕は3行以上にしない。"""
    if len(text) <= width:
        return text
    # 中央に最も近い句読点で切る
    marks = [m.end() for m in re.finditer(r"[、。]", text)]
    if marks:
        mid = len(text) / 2
        cut = min(marks, key=lambda i: abs(i - mid))
        if 0 < cut < len(text):
            return text[:cut].rstrip() + "\n" + text[cut:].lstrip()
    return text[:width] + "\n" + text[width:]


def build(project: Path) -> tuple[str, int, float]:
    meta = json.loads((project / "audio_meta.json").read_text(encoding="utf-8"))
    real = {
        int(v["frame"]): float(v["duration_s"])
        for v in meta.get("voices", [])
        if v.get("frame") is not None and v.get("duration_s")
    }
    # `pad_audio.py` が行頭・行末に足した無音。字幕は「語っている間」だけ出す
    # （足していない音声は 0。行末の 0.35 秒は生成時に焼き込まれた自然な間として残す）
    head = {int(v["frame"]): float(v.get("head_s") or 0) for v in meta.get("voices", []) if v.get("frame") is not None}
    extra_tail = {
        int(v["frame"]): max(0.0, float(v["tail_s"]) - 0.35)
        for v in meta.get("voices", [])
        if v.get("frame") is not None and v.get("tail_s") is not None
    }
    durations = frame_durations(project / "STORYBOARD.md")
    spoken = spoken_by_frame(project / "SCRIPT.md")

    blocks: list[str] = []
    clock = 0.0
    n = 0
    for frame in sorted(durations):
        # 音声があるフレームは実尺、無いフレームは STORYBOARD の見積もりを使う
        length = real.get(frame, durations[frame])
        text = spoken.get(frame, "").strip()
        if text:
            n += 1
            start = clock + head.get(frame, 0.0)
            end = clock + length - extra_tail.get(frame, 0.0)
            blocks.append(
                f"{n}\n{timestamp(start)} --> {timestamp(end)}\n"
                f"{wrap(text)}\n"
            )
        clock += length
    return "\n".join(blocks), n, clock


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="台本と音声メタから .srt を作る")
    ap.add_argument("project", help="Hyperframes プロジェクトのディレクトリ")
    ap.add_argument("--out", default="subtitles.ja.srt", help="書き出し先（プロジェクト内）")
    a = ap.parse_args(argv[1:])

    project = Path(a.project)
    for name in ("audio_meta.json", "STORYBOARD.md", "SCRIPT.md"):
        if not (project / name).is_file():
            print(f"FAIL: {project / name} がありません")
            return 1

    srt, n, total = build(project)
    out = project / a.out
    # Udemy は BOM 無し UTF-8 を期待する
    out.write_text(srt, encoding="utf-8", newline="\n")
    print(f"OK: {out} に {n} 件の字幕を書き出しました（動画の想定尺 {total:.1f}秒）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
