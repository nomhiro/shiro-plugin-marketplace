# -*- coding: utf-8 -*-
"""静止画フレームから「録画」`<basename>_rec.mp4` と台本の骨組みを作る（モードB）。

PC操作を伴わない回（設計・図解・ドキュメントの読み解き）や、Claude がブラウザを
操作して1状態ずつ撮った回では、連続した動画そのものが存在しない。そこで
**フレーム1枚＝1区間**として動画を組み立てる。

肝は**尺をナレーションから決める**こと。先にフレームの秒数を決めるとナレーションが
必ずはみ出す。尺の決め方は2通りあり、**実尺のほうを使う**。

  A. 実尺（推奨）  尺 = max(下限, 合成済み音声の実尺 + tail)
     `--audio-dir` か `--durations` を渡したときに使われる。
  B. 見積もり      尺 = max(下限, 文字数 / cps * 1.15 + 余白)
     音声がまだ無いときの下見用。

**B をそのまま完成尺にしない。** 見積もりに載せた余裕（headroom と余白）が、
そのまま無音として残る。実測では B で組むと録画パートの沈黙率が2割を超え、
区間によっては4秒以上、喋り終えた静止画を眺めることになった。
A に切り替えて `--tail-sec 2.0` とした7本では、沈黙率およそ10%、
1区間の最大無音 3.7〜4.1秒、本ごとのばらつき 0.1秒に収まった。

    1パス目  台本 → TTS（音声だけ先に合成する）
    2パス目  build_rec.py --audio-dir <音声> → フレームを組む

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

使い方（2パス目は --audio-dir を足すだけ）:
    python build_rec.py frames.json --frame-dir ./frames --out-dir ./lectures/00_intro \\
        --base "L0-2-3_実践_foundry-portal-tour" --slides slides.json \\
        --audio-dir ./lectures/00_intro/L0-2-3_実践_foundry-portal-tour_audio_rec
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # 画像サイズが取れないときはパディングのみで進める
    Image = None

DEFAULT_CPS = 5.7
DEFAULT_HEADROOM = 1.15   # TTS のばらつき分
DEFAULT_PAD_SEC = 1.0     # 区間末尾に残す無音（見積もりパス）
DEFAULT_MIN_SEC = 5.0
DEFAULT_TAIL_SEC = 2.0    # 実尺に足す末尾の無音。実測の最適値

AUDIO_EXT = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus")


def duration_for(text: str, cps: float, headroom: float, pad: float, floor: float) -> float:
    """見積もりパス：音声がまだ無いときだけ使う。"""
    return max(floor, round(len(text) / cps * headroom + pad, 2))


def duration_from_audio(sec: float, tail: float, floor: float) -> float:
    """実尺パス：合成済み音声の長さに末尾の無音を足す。"""
    return max(floor, round(sec + tail, 2))


def audio_seconds(path: Path) -> float:
    """音声の実尺（秒）。wav は標準ライブラリで、それ以外は ffprobe で測る。"""
    if path.suffix.lower() == ".wav":
        try:
            import wave
            with wave.open(str(path), "rb") as w:
                rate = w.getframerate()
                if rate:
                    return w.getnframes() / float(rate)
        except Exception:
            pass  # 圧縮された wav などは ffprobe に回す
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.strip():
        raise SystemExit(f"音声の長さを測れません: {path}")
    return float(out.stdout.strip())


def natural_key(p: Path):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", p.name)]


def resolve_audio(entries, audio_dir: Path) -> list[float]:
    """各区間に対応する音声の実尺を並べて返す。

    対応づけは2通り。フレーム定義に "audio" があればそれを使い、無ければ
    ディレクトリ内の音声を名前順に並べて**位置で**対応づける。後者は区間数と
    音声数が一致していることが前提なので、ずれていたら黙って進めずに止める。
    """
    if not audio_dir.is_dir():
        raise SystemExit(f"音声ディレクトリがありません: {audio_dir}")

    named = [e.get("audio") for e in entries]
    if all(named):
        paths = [audio_dir / n for n in named]
        missing = [p for p in paths if not p.exists()]
        if missing:
            raise SystemExit("音声が見つかりません: "
                             + ", ".join(p.name for p in missing))
        return [audio_seconds(p) for p in paths]
    if any(named):
        raise SystemExit('"audio" は全区間に書くか、全く書かないかのどちらかにしてください')

    files = sorted((f for f in audio_dir.iterdir()
                    if f.suffix.lower() in AUDIO_EXT), key=natural_key)
    pool = [f for f in files if "rec" in f.stem.lower()] or files
    if len(pool) != len(entries):
        head = ", ".join(f.name for f in pool[:8]) + (" …" if len(pool) > 8 else "")
        raise SystemExit(
            f"区間数({len(entries)})と音声数({len(pool)})が一致しません: {audio_dir}\n"
            f"  見つけた音声: {head}\n"
            "  スライドの音声が混ざっているか、区間を編集したあとの再合成が"
            'まだです。フレーム定義に "audio" を書いて明示することもできます。')
    return [audio_seconds(f) for f in pool]


def load_durations(path: Path, entries) -> list[float]:
    """--durations の JSON を読む。配列（位置で対応）か、フレーム名→秒 の辞書。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        if len(data) != len(entries):
            raise SystemExit(
                f"区間数({len(entries)})と秒数の件数({len(data)})が一致しません")
        return [float(x) for x in data]
    if isinstance(data, dict):
        out = []
        for i, e in enumerate(entries):
            for key in (e["frame"], Path(e["frame"]).stem, str(i + 1), str(i)):
                if key in data:
                    out.append(float(data[key]))
                    break
            else:
                raise SystemExit(f"秒数が見つかりません: {e['frame']}")
        return out
    raise SystemExit("--durations は配列か辞書で渡してください")


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
    t = round(t, 2)  # 59.996 を「00:60.00」と書かないよう、先に丸めてから分と秒に分ける
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
    ap.add_argument("--audio-dir", type=Path, default=None,
                    help="合成済み音声のディレクトリ。渡すと尺を**実尺**で決める（推奨）")
    ap.add_argument("--durations", type=Path, default=None,
                    help="区間ごとの音声秒数を書いた JSON（配列か フレーム名→秒 の辞書）")
    ap.add_argument("--tail-sec", type=float, default=DEFAULT_TAIL_SEC,
                    help="実尺に足す末尾の無音。実測の最適値は 2.0")
    ap.add_argument("--cps", type=float, default=DEFAULT_CPS,
                    help="見積もりパス用。実尺を渡したときは使われない")
    ap.add_argument("--headroom", type=float, default=DEFAULT_HEADROOM,
                    help="見積もりパス用。実尺を渡したときは使われない")
    ap.add_argument("--pad-sec", type=float, default=DEFAULT_PAD_SEC,
                    help="見積もりパスで各区間の末尾に残す無音")
    ap.add_argument("--min-sec", type=float, default=DEFAULT_MIN_SEC)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--video-only", action="store_true")
    a = ap.parse_args()

    entries = json.loads(a.frames_json.read_text(encoding="utf-8"))
    slides = json.loads(a.slides.read_text(encoding="utf-8")) if a.slides else []

    if a.audio_dir and a.durations:
        raise SystemExit("--audio-dir と --durations は同時に渡せません")
    if a.audio_dir:
        spoken = resolve_audio(entries, a.audio_dir)
    elif a.durations:
        spoken = load_durations(a.durations, entries)
    else:
        spoken = None

    if spoken is None:
        for e in entries:
            e["_dur"] = duration_for(e["text"], a.cps, a.headroom,
                                     a.pad_sec, a.min_sec)
    else:
        for e, sec in zip(entries, spoken):
            e["_spoken"] = sec
            e["_dur"] = duration_from_audio(sec, a.tail_sec, a.min_sec)

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
    dur_total = sum(e["_dur"] for e in entries)
    print(f"  録画パート {dur_total:.1f}s "
          f"({int(dur_total) // 60}:{dur_total % 60:04.1f}) / {len(entries)}区間")
    if spoken is None:
        print("  尺: 見積もり（文字数 / cps × headroom + 余白）"
              " ← 下見用。音声ができたら --audio-dir で組み直すこと")
    else:
        gaps = [e["_dur"] - e["_spoken"] for e in entries]
        ratio = sum(gaps) / dur_total * 100 if dur_total else 0.0
        worst = max(range(len(entries)), key=lambda i: gaps[i])
        print(f"  尺: 実尺 + {a.tail_sec:.1f}s")
        print(f"  沈黙率 {ratio:.1f}% / 最大の無音 {gaps[worst]:.1f}s"
              f"（録画{worst + 1}） ← 目安 10〜20%")
        if ratio > 20:
            print("  ! 沈黙が多すぎます。--tail-sec を下げるか、区間を統合してください")
    est = dur_total
    for s in slides:
        sec = len(s["text"]) / a.cps
        print(f"  スライド{s['n']}: {len(s['text'])}字 → 約{sec:.0f}s")
        est += sec
    print(f"  想定合計: {int(est) // 60}:{est % 60:04.1f}")
    if spoken is None:
        print("\n  次: transcript-check → TTS（--audio-only）"
              " → --audio-dir を付けて本スクリプトを再実行")
    else:
        print("\n  次: analyze --force → transcript-check → build --video-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
