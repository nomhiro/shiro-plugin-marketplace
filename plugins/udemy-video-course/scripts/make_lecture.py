"""レクチャー動画（Udemy の1本）を作る: 冒頭 → ユニット… → 末尾 の MP4 を連結し、字幕を統合する。

    python make_lecture.py L3-1 lecture-3-1-open supervised-classification-regression linear-regression \\
        logistic-regression svm-margin-kernel decision-tree ensemble-learning-slide lecture-3-1-close

出力: `<lectures_out_dir>/<lecture-id>/lecture.mp4`（`course.yaml`。既定 videos/_lectures） ／ `lecture.srt` ／ `concat.txt` ／ `build.json`

## 何をするか

- 各プロジェクトの `renders/video.mp4` を **ffmpeg の concat（再エンコードなし）** でつなぐ。
  Hyperframes の出力は同じ設定（H.264 / 30fps / 1920×1080 / AAC 48kHz）なので `-c copy` で足りる。
  **設定が食い違うと `-c copy` は壊れた動画を作る**ので、**連結の前に ffprobe で全本の設定を突き合わせ、違えば止める**。
- 各プロジェクトの `subtitles.ja.srt` を、**それまでの動画の長さ（実測）ぶんだけ後ろへずらして**1本にする
  （各 srt はプロジェクト先頭が 0 秒なので、累積オフセットが要る）。
- **つなぎ目に「間」を足さない。** 各行の行頭 0.6 秒・行末 1.2 秒の無音（`pad_audio.py`）が、すでに間になっている。

## 冪等
毎回作り直す（出力は上書き）。入力の MP4 は変更しない。
"""

from __future__ import annotations

import json
import re
import subprocess
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


def probe(mp4: Path) -> dict:
    """連結の可否を決める設定と、実尺（format.duration）を返す。"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels,pix_fmt:format=duration",
         "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), {})
    sig = (v["codec_name"], v["width"], v["height"], v["r_frame_rate"], v.get("pix_fmt"),
           a.get("codec_name"), a.get("sample_rate"), a.get("channels"))
    return {"sig": sig, "duration": float(j["format"]["duration"])}


TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def to_sec(t: str) -> float:
    h, m, s, ms = map(int, TS.match(t.strip()).groups())
    return h * 3600 + m * 60 + s + ms / 1000


def to_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def shift_srt(text: str, offset: float, start_index: int) -> tuple[list[str], int]:
    blocks = []
    n = start_index
    for b in re.split(r"\n\s*\n", text.strip()):
        lines = b.strip().splitlines()
        if len(lines) < 3:
            continue
        a, _, z = lines[1].partition("-->")
        n += 1
        blocks.append(f"{n}\n{to_ts(to_sec(a) + offset)} --> {to_ts(to_sec(z) + offset)}\n" + "\n".join(lines[2:]) + "\n")
    return blocks, n


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    lecture, units = argv[1], argv[2:]
    outdir = COURSE.path("lectures_out_dir") / lecture
    outdir.mkdir(parents=True, exist_ok=True)

    parts, missing = [], []
    for u in units:
        mp4 = COURSE.unit(u) / "renders" / "video.mp4"
        srt = COURSE.unit(u) / "subtitles.ja.srt"
        if not mp4.is_file():
            missing.append(u)
            continue
        parts.append((u, mp4, srt, probe(mp4)))
    if missing:
        print(f"FAIL: renders/video.mp4 が無い: {', '.join(missing)}")
        return 1

    sigs = {p[3]["sig"] for p in parts}
    if len(sigs) != 1:
        print("FAIL: 動画の設定が食い違うので `-c copy` で連結できない（再エンコードが要る）:")
        for u, _, _, info in parts:
            print(f"  {u}: {info['sig']}")
        return 1

    concat = outdir / "concat.txt"
    concat.write_text("".join(f"file '{p[1].as_posix()}'\n" for p in parts), encoding="utf-8", newline="\n")
    out = outdir / "lecture.mp4"
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(concat), "-c", "copy", str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        print("FAIL: ffmpeg concat:", r.stderr[-400:])
        return 1

    # 字幕: それまでの動画の実尺ぶんだけずらして1本にする
    blocks, n, offset = [], 0, 0.0
    starts = []
    for u, _, srt, info in parts:
        starts.append((u, round(offset, 3)))
        if srt.is_file():
            b, n = shift_srt(srt.read_text(encoding="utf-8"), offset, n)
            blocks += b
        else:
            print(f"  ※ {u}: subtitles.ja.srt が無い（字幕なしで連結）")
        offset += info["duration"]
    (outdir / "lecture.srt").write_text("\n".join(blocks), encoding="utf-8", newline="\n")

    total = probe(out)["duration"]
    (outdir / "build.json").write_text(json.dumps(
        {"lecture": lecture, "parts": [{"unit": u, "start_s": s} for u, s in starts],
         "sum_of_parts_s": round(offset, 3), "lecture_s": round(total, 3)},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    drift = total - offset
    print(f"OK: {out}\n  {len(parts)} 本 / 合計 {offset:.2f}秒 → 連結後 {total:.2f}秒（差 {drift:+.3f}秒）/ 字幕 {n} 件")
    if abs(drift) > 0.5:
        print("  ★ 連結後の尺と各本の尺の合計が 0.5 秒以上ずれている。字幕のずれを疑う")
    for u, s in starts:
        print(f"    {s:8.2f}s  {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
