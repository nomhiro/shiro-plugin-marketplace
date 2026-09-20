# -*- coding: utf-8 -*-
"""静止画フレームから「録画」`<basename>_rec.mp4` と台本の骨組みを作る（モードB）。

PC操作を伴わない回（設計・図解・ドキュメントの読み解き）や、Claude がブラウザを
操作して1状態ずつ撮った回では、連続した動画そのものが存在しない。そこで
**フレーム1枚＝1区間**として動画を組み立てる。

肝は**尺をナレーションから逆算する**こと。先にフレームの秒数を決めるとナレーションが
必ずはみ出す。各区間の尺は

    尺 = max(下限, 文字数 / cps * 1.15 + 余白)

で決め、その秒数でフレームを並べる。こうすると `transcript-check` が一発で通り、
タイムコードの調整が要らない。

フレームの合成規則:
  - **拡大縮小しない**のが原則。ブラウザのビューポートは呼び出しごとに数十px変わる
    ため、スケールし直すと区間ごとに文字の大きさが変わって見える。キャンバスへ
    **パディング**するだけにすれば、文字の大きさが揃う。
  - キャンバスより大きい画像（高解像度で書き出した図など）だけ、収まるように縮める。

入力は JSON（または Python から import して使う）:

    [
      {"frame": "f01.png", "title": "教材フォルダを開く", "text": "画面は…"},
      ...
    ]

使い方:
    python build_rec.py frames.json --frame-dir ./frames --out-dir ./lectures/00_intro \\
        --base "L0-2-3_実践_foundry-portal-tour" --slides slides.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # 画像サイズが取れないときはパディングのみで進める
    Image = None

DEFAULT_CPS = 5.7
DEFAULT_HEADROOM = 1.15   # TTS のばらつき分
DEFAULT_PAD_SEC = 1.0     # 区間末尾に残す無音
DEFAULT_MIN_SEC = 5.0


def duration_for(text: str, cps: float, headroom: float, pad: float, floor: float) -> float:
    return max(floor, round(len(text) / cps * headroom + pad, 2))


def build_video(entries, frame_dir: Path, out: Path, canvas: tuple[int, int],
                bg: str, fps: int, crf: int) -> None:
    W, H = canvas
    args, filt, concat = [], "", ""
    for i, e in enumerate(entries):
        p = frame_dir / e["frame"]
        if not p.exists():
            raise SystemExit(f"フレームが見つかりません: {p}")
        big = False
        if Image is not None:
            w, h = Image.open(p).size
            big = w > W or h > H
        args += ["-loop", "1", "-t", str(e["_dur"]), "-i", str(p)]
        if big:  # 図版など：収まるように縮めてから中央へ
            filt += (f"[{i}]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                     f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={bg},setsar=1,fps={fps}[v{i}];")
        else:    # スクリーンショット：拡大縮小せずパディングだけ
            filt += (f"[{i}]pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={bg},"
                     f"setsar=1,fps={fps}[v{i}];")
        concat += f"[v{i}]"
    subprocess.run(
        ["ffmpeg", "-v", "error", *args, "-filter_complex",
         f"{filt}{concat}concat=n={len(entries)}:v=1:a=0[v]", "-map", "[v]",
         "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
         "-pix_fmt", "yuv420p", str(out), "-y"], check=True)


def mmss(t: float) -> str:
    return f"{int(t) // 60:02d}:{t % 60:05.2f}"


def write_transcript(entries, slides, out: Path, title: str) -> float:
    """導入スライド → 録画 → まとめスライド のサンドイッチで台本を書き出す。"""
    head = [s for s in slides if s.get("where", "intro") == "intro"]
    tail = [s for s in slides if s.get("where") == "outro"]
    lines = [f"# {title}", ""]
    for s in head:
        lines += [f"## スライド{s['n']}: {s['title']}", "", s["text"], ""]
    t = 0.0
    for i, e in enumerate(entries, 1):
        lines += [f"## 録画{i} [{mmss(t)}-{mmss(t + e['_dur'])}]: {e['title']}", "",
                  e["text"], ""]
        t += e["_dur"]
    for s in tail:
        lines += [f"## スライド{s['n']}: {s['title']}", "", s["text"], ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_json", type=Path, help='[{"frame","title","text"}, ...]')
    ap.add_argument("--frame-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--base", required=True, help="レクチャーの basename")
    ap.add_argument("--slides", type=Path, default=None,
                    help='[{"n","title","text","where":"intro|outro"}, ...]')
    ap.add_argument("--title", default=None, help="台本の見出し")
    ap.add_argument("--canvas", default="1600x816")
    ap.add_argument("--bg", default="black")
    ap.add_argument("--cps", type=float, default=DEFAULT_CPS)
    ap.add_argument("--headroom", type=float, default=DEFAULT_HEADROOM)
    ap.add_argument("--pad-sec", type=float, default=DEFAULT_PAD_SEC,
                    help="各区間の末尾に残す無音。画面を見せる回は 2.5〜3.5 を推奨")
    ap.add_argument("--min-sec", type=float, default=DEFAULT_MIN_SEC)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--video-only", action="store_true")
    a = ap.parse_args()

    entries = json.loads(a.frames_json.read_text(encoding="utf-8"))
    slides = json.loads(a.slides.read_text(encoding="utf-8")) if a.slides else []
    for e in entries:
        e["_dur"] = duration_for(e["text"], a.cps, a.headroom, a.pad_sec, a.min_sec)

    canvas = tuple(int(x) for x in a.canvas.split("x"))
    a.out_dir.mkdir(parents=True, exist_ok=True)
    rec = a.out_dir / f"{a.base}_rec.mp4"
    if rec.exists():
        backup = a.out_dir / f"{a.base}_rec.previous.mp4"
        if not backup.exists():
            rec.replace(backup)
            print(f"  既存の録画を退避しました: {backup.name}")
    build_video(entries, a.frame_dir, rec, canvas, a.bg, a.fps, a.crf)

    total = 0.0
    if not a.video_only:
        total = write_transcript(
            entries, slides, a.out_dir / f"{a.base}_transcript_rec.md",
            a.title or f"{a.base} ナレーション台本（録画パート版）")

    print(f"■ build-rec: {a.base}")
    print(f"  録画パート {total:.1f}s ({int(total) // 60}:{total % 60:04.1f}) / {len(entries)}区間")
    est = total
    for s in slides:
        sec = len(s["text"]) / a.cps
        print(f"  スライド{s['n']}: {len(s['text'])}字 → 約{sec:.0f}s")
        est += sec
    print(f"  想定合計: {int(est) // 60}:{est % 60:04.1f}")
    print("\n  次: analyze --force → （必要なら shift_lead）→ transcript-check → build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
