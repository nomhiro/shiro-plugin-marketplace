#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""実践（ハンズオン）レクチャーの PC操作録画に AI音声ナレーションを付けて動画化する。

動画講座向け。姉妹スキル `make-lecture-movie` の `lecture_movie.py` を
import して、TTS・pptx→PNG化・スライドセグメント合成・各種定数を**再利用**する
（コピーしない）。座学（スライドのみ）との違いは、制作者の PC操作録画
（`<basename>_rec.mp4` 群）を本編素材とし、その録画内容に沿った・録画尺に収まる
ナレーションを乗せる点にある。

構成（サンドイッチ）:
  導入スライド → PC録画本編（複数セグメント可） → まとめスライド
台本 `<basename>_transcript_rec.md` に、スライドと録画セグメントを**ドキュメント順
＝動画順**で記述する:
  ## スライド1: タイトル
  （導入ナレーション）
  ## 録画1 [00:12-01:48]: venv作成と依存導入
  （このセグメントのナレーション。録画尺の文字数バジェット内）
  ## 録画2 [01:48-03:05]: .env設定
  ...
  ## スライド6: まとめ

サブコマンド:
  calibrate                 座学成果物から日本語TTS実効速度(net文字/秒)を実測
  analyze <ID>              録画を正規化→フレーム抽出し、時刻対応表を出力（区切り検討用）
  transcript-check <ID>     台本のタイムコード整合・文字数バジェット超過を検査
  build <ID>                TTS→スライドPNG→セグメント合成→結合で <basename>.mp4 を生成

出力:
  <section>/<basename>_rec.work/rec_norm.mp4      正規化済み録画（タイムコード基準）
  <section>/<basename>_rec.work/frames/*.png      analyze のフレーム
  <section>/<basename>_audio_rec/<key>.wav        セグメント別ナレーション（key=slide_NN/rec_NN）
  <section>/<basename>.mp4                         完成動画
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

# Windows既定(cp932)だと ▶ ✓ 等で UnicodeEncodeError になるため UTF-8 化
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------------------
# lecture_movie（make-lecture-movie スキル）を import して再利用する
#   practice_movie.py から見た相対 `../../make-lecture-movie/scripts` に存在する。
#   （.claude/skills/make-practice-movie/scripts → skills → make-lecture-movie/scripts）
# ---------------------------------------------------------------------------
_LM_DIR = (Path(__file__).resolve().parent / ".." / ".." /
           "make-lecture-movie" / "scripts").resolve()
if str(_LM_DIR) not in sys.path:
    sys.path.insert(0, str(_LM_DIR))
try:
    import lecture_movie as lm  # noqa: E402
except ImportError as e:  # pragma: no cover
    sys.exit(f"lecture_movie の import に失敗しました（{_LM_DIR} を確認）: {e}")

# lm から再利用する定数（別名で束ねる）
FFMPEG = lm.FFMPEG
FFPROBE = lm.FFPROBE
W, H, FPS = lm.VIDEO_WIDTH, lm.VIDEO_HEIGHT, lm.VIDEO_FPS

# ---------------------------------------------------------------------------
# 実践固有の定数
# ---------------------------------------------------------------------------
# 日本語TTS実効速度（net文字/秒）。座学成果物から実測（calibrate で再確認できる）。
CPS_EFFECTIVE = 5.3
# 文字数バジェットの充填率。末尾に無音マージンを残して TTS 速度ぶれを吸収する。
FILL_RATIO = 0.9
# 録画セグメントの既定パラメータ
ORIG_VOLUME_DEFAULT = 0.18      # 元音声を残す音量（ナレーションとミックス）
REC_LEAD_SECONDS_DEFAULT = 0.3  # 録画開始からナレーション開始までのディレイ
TOLERANCE_DEFAULT = 0.15        # ナレーションがセグメントより長いときの許容超過率
FRAMES_MAX_DEFAULT = 60         # analyze のフレーム抽出上限
FRAME_W, FRAME_H = 1280, 720    # 抽出フレームの解像度

# 録画の正規化・セグメント合成で使う黒背景パッド（スライドは lm._VF の白背景）
_VF_BLACK = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
             f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")


# ---------------------------------------------------------------------------
# 小さなヘルパ
# ---------------------------------------------------------------------------
def _run_ff(cmd: list) -> subprocess.CompletedProcess:
    """ffmpeg/ffprobe を実行する。失敗時は stderr 末尾を添えて CalledProcessError。"""
    printable = " ".join(str(c) for c in cmd)
    print(f"  $ {printable[:300]}")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-8:])
        raise subprocess.CalledProcessError(proc.returncode, cmd,
                                            output=proc.stdout, stderr=tail)
    return proc


def _net_chars(text: str) -> int:
    """空白・改行を除いた「読み上げ実文字数」を返す（全角空白 U+3000 も除去）。"""
    return len(re.sub(r"\s", "", text))


def char_budget(seconds: float, cps: float = CPS_EFFECTIVE,
                fill_ratio: float = FILL_RATIO) -> int:
    """録画セグメント尺 T 秒に収まるナレーションの目安文字数。"""
    return int(math.floor(cps * fill_ratio * seconds))


def _mmss(t: float) -> str:
    """秒を MM:SS 表記へ。"""
    t = max(0.0, t)
    m = int(t // 60)
    s = int(round(t - m * 60))
    if s == 60:
        m += 1
        s = 0
    return f"{m:02d}:{s:02d}"


def _parse_timecode(tc: str) -> float:
    """MM:SS / HH:MM:SS（小数秒・全角コロン許容）を秒(float)へ変換。"""
    tc = tc.strip().replace("：", ":")
    try:
        parts = [float(p) for p in tc.split(":")]
    except ValueError:
        raise ValueError(f"不正なタイムコード: {tc!r}")
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"不正なタイムコード（MM:SS か HH:MM:SS）: {tc!r}")


def _wav_seconds(path: Path) -> float:
    """wave モジュールで wav の実尺(秒)を返す（LINEAR16 24kHz/mono 前提）。"""
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        return w.getnframes() / float(rate) if rate else 0.0


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _is_fresh(out: Path, inputs: list[Path]) -> bool:
    """out が全 inputs より新しければ True（再生成不要）。"""
    try:
        om = out.stat().st_mtime
    except FileNotFoundError:
        return False
    for p in inputs:
        try:
            if om < p.stat().st_mtime:
                return False
        except FileNotFoundError:
            return False
    return True


# ---------------------------------------------------------------------------
# 台本パース（スライド／録画セグメントをドキュメント順に）
# ---------------------------------------------------------------------------
@dataclass
class SlideSeg:
    page: int          # pptx のページ番号
    label: str
    text: str
    order: int         # ドキュメント順（動画順）


@dataclass
class RecSeg:
    index: int         # 録画N の N
    start: float       # rec_norm.mp4 基準の開始秒
    end: float         # 同 終了秒
    label: str
    text: str
    order: int


_SLIDE_RE = re.compile(r"^##\s*スライド\s*(\d+)\s*[:：]?\s*(.*)$")
_REC_RE = re.compile(r"^##\s*録画\s*(\d+)\s*\[([^\]]+)\]\s*[:：]?\s*(.*)$")
_HEAD_RE = re.compile(r"(?m)^##(?!#).*$")   # h2 のみ（h3 以降は本文扱い）


def parse_practice_transcript(path: Path) -> list:
    """`## スライドN:` と `## 録画N [MM:SS-MM:SS]:` を順序どおりにパースする。

    見出しの本文（ナレーション）は次の h2 見出しまで。`---` 区切りは除去。
    スライド/録画以外の h2（あれば）は無視し、その本文も破棄する。
    """
    text = path.read_text(encoding="utf-8")
    heads = list(_HEAD_RE.finditer(text))
    segs: list = []
    order = 0
    for i, h in enumerate(heads):
        line = h.group(0)
        body_start = h.end()
        body_end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[body_start:body_end]
        body = re.sub(r"(?m)^---\s*$", "", body).strip()

        ms = _SLIDE_RE.match(line)
        if ms:
            segs.append(SlideSeg(page=int(ms.group(1)), label=ms.group(2).strip(),
                                 text=body, order=order))
            order += 1
            continue
        mr = _REC_RE.match(line)
        if mr:
            span = mr.group(2)
            parts = re.split(r"\s*[-–—]\s*", span.strip())
            parts = [p for p in parts if p.strip()]
            if len(parts) < 2:
                raise ValueError(f"録画見出しのタイムコードが不正です: {line!r}")
            start = _parse_timecode(parts[0])
            end = _parse_timecode(parts[-1])
            segs.append(RecSeg(index=int(mr.group(1)), start=start, end=end,
                               label=mr.group(3).strip(), text=body, order=order))
            order += 1
    return segs


def _seg_key(s) -> str:
    """音声ファイル／manifest のキー（slide_NN / rec_NN）。"""
    return f"slide_{s.page:02d}" if isinstance(s, SlideSeg) else f"rec_{s.index:02d}"


# ---------------------------------------------------------------------------
# 入力解決（レクチャーID → 各ファイルパス）
# ---------------------------------------------------------------------------
@dataclass
class PracticeJob:
    basename: str
    section_dir: Path
    pptx: Path
    transcript: Path        # 既存 _transcript.md（スライドパートの流用元。無い場合あり）
    transcript_rec: Path    # 実践用台本 _transcript_rec.md
    rec_parts: list         # _rec.mp4 単体 or _rec1.mp4,_rec2.mp4... 連番（自然順）
    work_dir: Path          # <basename>_rec.work
    rec_norm: Path          # work/rec_norm.mp4
    frames_dir: Path        # work/frames
    png_dir: Path           # work/png
    seg_dir: Path           # work/segs
    audio_dir: Path         # <basename>_audio_rec
    out_mp4: Path           # <basename>.mp4
    repo_root: Path


def _find_rec_parts(section_dir: Path, basename: str) -> list:
    """`<basename>_rec.mp4` 単体、無ければ `<basename>_rec1.mp4,...` を自然順で返す。"""
    single = section_dir / f"{basename}_rec.mp4"
    if single.exists():
        return [single]
    numbered = list(section_dir.glob(f"{basename}_rec[0-9]*.mp4"))

    def _num(p: Path) -> int:
        m = re.search(re.escape(basename) + r"_rec(\d+)\.mp4$", p.name)
        return int(m.group(1)) if m else 0

    return sorted(numbered, key=_num)


def resolve_practice_job(spec: str, lectures_dir: Path) -> PracticeJob:
    """レクチャーID/グロブ/パスから実践ジョブを解決する。"""
    p = Path(spec)
    if p.exists() and p.is_file():
        name = p.name
        section_dir = p.parent
        if name.endswith("_transcript_rec.md"):
            basename = name[: -len("_transcript_rec.md")]
        elif name.endswith("_transcript.md"):
            basename = name[: -len("_transcript.md")]
        elif p.suffix.lower() == ".pptx":
            basename = p.stem
        else:
            sys.exit(f"未対応の入力です（.pptx / *_transcript.md / *_transcript_rec.md）: {p}")
    else:
        # ID/グロブ → lm._spec_to_glob で `*_transcript.md` を検索（無ければ .pptx）
        pattern = lm._spec_to_glob(spec)
        matches = sorted(lectures_dir.glob(f"**/{pattern}"))
        if matches:
            if len(matches) > 1:
                prac = [m for m in matches
                        if lm.is_practice(m.name[: -len("_transcript.md")])]
                matches = prac or matches
            src = matches[0]
            basename = src.name[: -len("_transcript.md")]
            section_dir = src.parent
        else:
            pat2 = re.sub(r"-[xX*]$", "-*", spec.strip())
            if "*" not in pat2:
                pat2 += "*"
            pptx_matches = sorted(lectures_dir.glob(f"**/{pat2}.pptx"))
            if not pptx_matches:
                sys.exit(f"'{spec}' に一致するレクチャー（*_transcript.md / *.pptx）が "
                         f"{lectures_dir} 配下に見つかりません。")
            src = pptx_matches[0]
            basename = src.stem
            section_dir = src.parent

    work_dir = section_dir / f"{basename}_rec.work"
    return PracticeJob(
        basename=basename,
        section_dir=section_dir,
        pptx=section_dir / f"{basename}.pptx",
        transcript=section_dir / f"{basename}_transcript.md",
        transcript_rec=section_dir / f"{basename}_transcript_rec.md",
        rec_parts=_find_rec_parts(section_dir, basename),
        work_dir=work_dir,
        rec_norm=work_dir / "rec_norm.mp4",
        frames_dir=work_dir / "frames",
        png_dir=work_dir / "png",
        seg_dir=work_dir / "segs",
        audio_dir=section_dir / f"{basename}_audio_rec",
        out_mp4=section_dir / f"{basename}.mp4",
        repo_root=lm.find_repo_root(section_dir),
    )


# ---------------------------------------------------------------------------
# 録画の正規化（各パート → 1920x1080/30fps CFR/AAC 48k stereo → concat）
# ---------------------------------------------------------------------------
def _has_audio(path: Path) -> bool:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return bool(out.stdout.strip())


def _audio_channels(path: Path) -> int:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=channels", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return int(out.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0


def _ensure_stereo(seg: Path) -> None:
    """セグメント音声をステレオへ揃える。

    lm._segment_with_audio は TTS wav（mono）をそのまま AAC 化するため、
    録画セグメント（stereo）とチャンネル構成が混在し、concat の `-c copy` で
    再生互換性の問題を起こしうる。映像は copy し音声のみ再エンコードする。
    """
    if _audio_channels(seg) == 2:
        return
    tmp = seg.with_suffix(".stereo.mp4")
    _run_ff([FFMPEG, "-y", "-i", str(seg), "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-movflags", "+faststart", str(tmp)])
    tmp.replace(seg)


def _normalize_one(src: Path, out: Path) -> None:
    """1パートを 1920x1080黒パッド / 30fps CFR / AAC 48k stereo に正規化。

    音声トラックが無い録画には anullsrc で無音ステレオを付与し、以降の
    フィルタ・ミックスを均一に扱えるようにする。
    """
    vf = f"{_VF_BLACK},fps={FPS}"
    if _has_audio(src):
        cmd = [FFMPEG, "-y", "-i", str(src),
               "-vf", vf, "-r", str(FPS),
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               "-movflags", "+faststart", str(out)]
    else:
        cmd = [FFMPEG, "-y", "-i", str(src),
               "-f", "lavfi", "-i",
               "anullsrc=channel_layout=stereo:sample_rate=48000",
               "-vf", vf, "-r", str(FPS),
               "-map", "0:v:0", "-map", "1:a",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               "-shortest", "-movflags", "+faststart", str(out)]
    _run_ff(cmd)


def normalize_recording(job: PracticeJob, *, force: bool = False) -> Path:
    """録画パート群を正規化し concat して `rec_norm.mp4` を作る。既存が新しければskip。"""
    if not job.rec_parts:
        sys.exit(f"録画ファイルが見つかりません。"
                 f"{job.section_dir}\\{job.basename}_rec.mp4"
                 f"（複数なら _rec1.mp4,_rec2.mp4…）を配置してください。")
    job.work_dir.mkdir(parents=True, exist_ok=True)
    if not force and _is_fresh(job.rec_norm, job.rec_parts):
        print(f"  = skip 正規化（既存が入力より新しい）: {job.rec_norm.name}")
        return job.rec_norm

    print(f"  録画パート {len(job.rec_parts)} 本を正規化 → {job.rec_norm.name}")
    norm_parts: list[Path] = []
    for i, part in enumerate(job.rec_parts, 1):
        np_ = job.work_dir / f"rec_part_{i:02d}.mp4"
        _normalize_one(part, np_)
        norm_parts.append(np_)

    listfile = job.work_dir / "rec_concat.txt"
    listfile.write_text(
        "\n".join(f"file '{str(p).replace(chr(92), '/')}'" for p in norm_parts) + "\n",
        encoding="utf-8")
    try:
        _run_ff([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
                 "-c", "copy", "-movflags", "+faststart", str(job.rec_norm)])
    except subprocess.CalledProcessError:
        _run_ff([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
                 "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                 "-movflags", "+faststart", str(job.rec_norm)])
    return job.rec_norm


# ---------------------------------------------------------------------------
# フレーム抽出（区切り検討用）
# ---------------------------------------------------------------------------
def _parse_frame_scale(spec: str) -> tuple[int, int]:
    """`1280x720` / `1280:720` を (幅, 高さ) へ変換。"""
    m = re.fullmatch(r"\s*(\d+)\s*[x:×]\s*(\d+)\s*", spec)
    if not m:
        raise argparse.ArgumentTypeError(
            f"--frame-scale は 1280x720 の形式で指定してください: {spec!r}")
    return int(m.group(1)), int(m.group(2))


def extract_frames(rec_norm: Path, frames_dir: Path,
                   max_frames: int = FRAMES_MAX_DEFAULT,
                   frame_scale: tuple[int, int] = (FRAME_W, FRAME_H)) -> tuple[list, float]:
    """rec_norm から等間隔にフレームを抽出する。ファイル名に時刻を埋め込む。

    返り値: ([(index, seconds, path), ...], 録画総尺秒)
    """
    fw, fh = frame_scale
    dur = lm._probe_duration(rec_norm)
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame_*.png"):
        old.unlink()
    if dur <= 0 or max_frames <= 0:
        return [], dur
    interval = dur / max_frames
    results: list = []
    for i in range(max_frames):
        t = i * interval
        if t >= dur:
            break
        m, s = int(t // 60), int(t % 60)
        out = frames_dir / f"frame_{i + 1:04d}_{m:03d}m{s:02d}s.png"
        _run_ff([FFMPEG, "-y", "-ss", f"{t:.3f}", "-i", str(rec_norm),
                 "-frames:v", "1", "-vf", f"scale={fw}:{fh}",
                 str(out)])
        results.append((i + 1, t, out))
    return results, dur


# ---------------------------------------------------------------------------
# 録画セグメント合成（元音声低音量 ＋ ナレーションをミックス）
# ---------------------------------------------------------------------------
def build_rec_segment(rec_norm: Path, start: float, end: float,
                      narr_wav: Path | None, out: Path, *,
                      orig_volume: float = ORIG_VOLUME_DEFAULT,
                      rec_lead_seconds: float = REC_LEAD_SECONDS_DEFAULT,
                      tolerance: float = TOLERANCE_DEFAULT) -> tuple[str, dict]:
    """録画区間 [start,end] を切り出し、元音声(低音量)とナレーションをミックスする。

    ナレーション所要 = リード(先頭ディレイ) + wav実尺。これがセグメント尺 T 以下なら
    L=T（apad で末尾無音を吸収）。超えるときは映像を tpad(clone) でフリーズ延長して
    L=所要 に合わせる。超過率が tolerance を超える場合も強制フィットするが、status
    を "over" で返し呼び出し側が「要台本短縮」として報告する。

    返り値: (status, info)   status ∈ {"ok","freeze","over"}
    """
    T = end - start
    if T <= 0:
        raise ValueError(f"録画セグメント長が不正です: start={start} end={end}")

    have_narr = bool(narr_wav and Path(narr_wav).exists())
    d = lm._probe_duration(narr_wav) if have_narr else 0.0
    required = (rec_lead_seconds + d) if have_narr else 0.0

    freeze = 0.0
    status = "ok"
    L = T
    if have_narr and required > T:
        freeze = required - T
        L = required
        status = "freeze" if (freeze / T) <= tolerance else "over"

    lead_ms = int(rec_lead_seconds * 1000)
    vf = f"[0:v]{_VF_BLACK},fps={FPS}"
    if freeze > 0:
        vf += f",tpad=stop_mode=clone:stop_duration={freeze:.3f}"
    vf += "[v]"

    if have_narr:
        af = (f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,"
              f"volume={orig_volume},apad[oa];"
              f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,"
              f"adelay={lead_ms}:all=1,apad[na];"
              f"[oa][na]amix=inputs=2:duration=longest:normalize=0[a]")
        inputs = ["-ss", f"{start:.3f}", "-t", f"{T:.3f}", "-i", str(rec_norm),
                  "-i", str(narr_wav)]
    else:
        # ナレーション無し（台本にセグメント本文が無い場合）は元音声のみ
        af = "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[a]"
        inputs = ["-ss", f"{start:.3f}", "-t", f"{T:.3f}", "-i", str(rec_norm)]

    filter_complex = vf + ";" + af
    out.parent.mkdir(parents=True, exist_ok=True)
    _run_ff([FFMPEG, "-y", *inputs,
             "-filter_complex", filter_complex,
             "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-t", f"{L:.3f}", "-movflags", "+faststart", str(out)])
    return status, {"T": T, "d": d, "required": required, "L": L, "freeze": freeze}


# ---------------------------------------------------------------------------
# 最終結合（lm.build_lecture_video と同パターン）
# ---------------------------------------------------------------------------
def _concat_segments(seg_files: list, out_mp4: Path, work_dir: Path) -> None:
    listfile = work_dir / "segments.txt"
    listfile.write_text(
        "\n".join(f"file '{str(s).replace(chr(92), '/')}'" for s in seg_files) + "\n",
        encoding="utf-8")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run_ff([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
                 "-c", "copy", "-movflags", "+faststart", str(out_mp4)])
    except subprocess.CalledProcessError:
        _run_ff([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
                 "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                 "-movflags", "+faststart", str(out_mp4)])


# ---------------------------------------------------------------------------
# 音声キャッシュ（manifest: key → sha1(本文)）
# ---------------------------------------------------------------------------
def _load_manifest(audio_dir: Path) -> dict:
    mf = audio_dir / ".manifest.json"
    if mf.exists():
        try:
            return json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_manifest(audio_dir: Path, data: dict) -> None:
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / ".manifest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# サブコマンド: calibrate
# ---------------------------------------------------------------------------
def cmd_calibrate(args) -> int:
    lectures_dir = Path(args.lectures_dir).resolve()
    transcripts = sorted(lectures_dir.glob("**/*_transcript.md"))
    rows: list = []
    total_chars = 0
    total_secs = 0.0
    for t in transcripts:
        basename = t.name[: -len("_transcript.md")]
        if lm.is_practice(basename):
            continue
        audio_dir = t.parent / f"{basename}_audio"
        if not audio_dir.exists():
            continue
        tr = lm.parse_transcript(t)
        if not tr:
            continue
        segs = lm.plan_segments(max(tr), tr)
        lec_chars = 0
        lec_secs = 0.0
        n = 0
        for seg in segs:
            if not seg.text:
                continue
            wav = audio_dir / seg.speech_name
            if not wav.exists():
                continue
            try:
                secs = _wav_seconds(wav)
            except Exception:
                continue
            if secs <= 0:
                continue
            lec_chars += _net_chars(seg.text)
            lec_secs += secs
            n += 1
        if lec_secs > 0:
            rows.append((basename, n, lec_chars, lec_secs, lec_chars / lec_secs))
            total_chars += lec_chars
            total_secs += lec_secs

    if not rows:
        print(f"座学 transcript と音声(_audio/speech_NN.wav)のペアが "
              f"{lectures_dir} 配下に見つかりませんでした。")
        return 1

    print("■ calibrate: 座学成果物から日本語TTS実効速度(net文字/秒)を実測")
    print(f"\n  {'レクチャー':<44}{'seg':>4}{'net文字':>9}{'秒':>9}{'cps':>7}")
    for b, n, c, s, cps in sorted(rows):
        print(f"  {b:<44}{n:>4}{c:>9}{s:>9.1f}{cps:>7.2f}")
    overall = total_chars / total_secs
    print(f"\n  全体: {len(rows)}レクチャー / net {total_chars}文字 / "
          f"{total_secs:.1f}秒 → 実効 cps = {overall:.3f}")
    print(f"  現在の既定: CPS_EFFECTIVE={CPS_EFFECTIVE} / FILL_RATIO={FILL_RATIO} "
          f"→ char_budget(60s)={char_budget(60)} 文字")
    return 0


# ---------------------------------------------------------------------------
# サブコマンド: analyze
# ---------------------------------------------------------------------------
def cmd_analyze(args) -> int:
    lectures_dir = Path(args.lectures_dir).resolve()
    job = resolve_practice_job(args.id, lectures_dir)
    print(f"■ analyze: {job.basename}")
    if not job.rec_parts:
        print(f"✗ 録画ファイルが見つかりません: "
              f"{job.section_dir}\\{job.basename}_rec.mp4（複数なら _rec1.mp4…）")
        return 1
    print(f"  録画パート: {len(job.rec_parts)} 本")
    for p in job.rec_parts:
        print(f"    - {p.name}")

    normalize_recording(job, force=args.force)
    frames, dur = extract_frames(job.rec_norm, job.frames_dir, args.max_frames,
                                 frame_scale=args.frame_scale)
    print(f"\n  録画総尺: {_mmss(dur)} ({dur:.1f}s) / "
          f"抽出フレーム {len(frames)} 枚 → {job.frames_dir}")
    print(f"\n  {'idx':>4}  {'時刻':>6}  ファイル")
    for idx, t, path in frames:
        print(f"  {idx:>4}  {_mmss(t):>6}  {path.name}")
    print(f"\n  次のステップ: 上記フレームを確認し、区切り（録画N [MM:SS-MM:SS]）を決めて")
    print(f"  {job.transcript_rec.name} を作成 → transcript-check → build")
    return 0


# ---------------------------------------------------------------------------
# サブコマンド: transcript-check
# ---------------------------------------------------------------------------
def cmd_transcript_check(args) -> int:
    lectures_dir = Path(args.lectures_dir).resolve()
    job = resolve_practice_job(args.id, lectures_dir)
    if not job.transcript_rec.exists():
        print(f"✗ 台本が見つかりません: {job.transcript_rec}")
        return 1
    segs = parse_practice_transcript(job.transcript_rec)
    n_slide = sum(1 for s in segs if isinstance(s, SlideSeg))
    n_rec = sum(1 for s in segs if isinstance(s, RecSeg))

    num_pages = lm.count_slides(job.pptx) if job.pptx.exists() else None
    rec_dur = lm._probe_duration(job.rec_norm) if job.rec_norm.exists() else None

    print(f"■ transcript-check: {job.basename}")
    print(f"  セグメント: スライド {n_slide} / 録画 {n_rec}")
    if num_pages is not None:
        print(f"  pptx ページ数: {num_pages}")
    if rec_dur is not None:
        print(f"  録画総尺(rec_norm): {_mmss(rec_dur)} ({rec_dur:.1f}s)")
    else:
        print("  ⚠ rec_norm.mp4 が未生成のため録画総尺との照合はスキップ"
              "（analyze/build で生成されます）")

    problems = 0
    prev_end: float | None = None
    for s in segs:
        if isinstance(s, SlideSeg):
            if num_pages is not None and not (1 <= s.page <= num_pages):
                print(f"  ✗ スライド{s.page}: pptx ページ範囲(1..{num_pages})外")
                problems += 1
            continue
        # RecSeg
        if s.end <= s.start:
            print(f"  ✗ 録画{s.index}: 終了({_mmss(s.end)}) ≤ 開始({_mmss(s.start)})")
            problems += 1
        if prev_end is not None and s.start < prev_end - 1e-6:
            print(f"  ✗ 録画{s.index}: 開始({_mmss(s.start)})が前セグメント終了"
                  f"({_mmss(prev_end)})より前（単調増加でない）")
            problems += 1
        prev_end = s.end
        if rec_dur is not None and s.end > rec_dur + 0.5:
            print(f"  ✗ 録画{s.index}: 終了({_mmss(s.end)})が録画総尺"
                  f"({_mmss(rec_dur)})を超過")
            problems += 1
        T = s.end - s.start
        nb = char_budget(T, args.cps, args.fill_ratio)
        nc = _net_chars(s.text)
        if nc > nb:
            print(f"  ⚠ 録画{s.index} [{_mmss(s.start)}-{_mmss(s.end)}] {s.label}: "
                  f"文字数 {nc} > バジェット {nb}（{T:.0f}s, cps={args.cps}×{args.fill_ratio}）"
                  f" → 約 {nc - nb} 文字オーバー")
            problems += 1
        else:
            print(f"  ✓ 録画{s.index} [{_mmss(s.start)}-{_mmss(s.end)}] {s.label}: "
                  f"文字数 {nc}/{nb}")

    if problems:
        print(f"\n✗ 問題 {problems} 件。台本を修正してください。")
        return 1
    print("\n✓ 問題なし")
    return 0


# ---------------------------------------------------------------------------
# サブコマンド: build
# ---------------------------------------------------------------------------
def cmd_build(args) -> int:
    lectures_dir = Path(args.lectures_dir).resolve()
    job = resolve_practice_job(args.id, lectures_dir)
    if not job.transcript_rec.exists():
        print(f"✗ 台本が見つかりません: {job.transcript_rec}")
        print("  analyze でフレームを確認し、_transcript_rec.md を作成してください。")
        return 1
    segs = parse_practice_transcript(job.transcript_rec)
    if not segs:
        print(f"✗ 台本にスライド/録画セグメントがありません: {job.transcript_rec}")
        return 1

    do_audio = not args.video_only
    do_video = not args.audio_only
    n_slide = sum(1 for s in segs if isinstance(s, SlideSeg))
    n_rec = sum(1 for s in segs if isinstance(s, RecSeg))

    print(f"■ build: {job.basename}")
    print(f"  セグメント: スライド {n_slide} / 録画 {n_rec}")

    instruction_path = Path(args.instruction) if args.instruction \
        else job.repo_root / "vertexai-tts-instruction.md"
    voice, style_prompt = lm.load_voice_and_style(instruction_path,
                                                  default_voice="Callirrhoe")
    if args.voice:
        voice = args.voice

    over_list: list = []
    failures: list = []

    with tempfile.TemporaryDirectory(prefix="practice_movie_") as td:
        tmp = Path(td)

        # ---- 音声フェーズ ----
        if do_audio:
            print(f"\n▶ 音声生成 (model={args.model}, voice={voice})")
            manifest = _load_manifest(job.audio_dir)
            for s in segs:
                if not s.text:
                    continue
                key = _seg_key(s)
                out_wav = job.audio_dir / f"{key}.wav"
                digest = _sha1(s.text)
                if out_wav.exists() and not args.force and manifest.get(key) == digest:
                    print(f"  = skip {key}.wav（本文不変）")
                    continue
                print(f"  + {key}.wav")
                try:
                    lm.synthesize_speech_file(
                        text=s.text, style_prompt=style_prompt, voice=voice,
                        model=args.model, language_code=args.language_code,
                        out_wav=out_wav, tmp_dir=tmp, max_chars=args.max_chunk_chars,
                        chunk_gap=args.chunk_gap_seconds)
                    manifest[key] = digest
                    _save_manifest(job.audio_dir, manifest)
                except Exception as e:
                    msg = str(e).splitlines()[0][:160]
                    print(f"    ! 失敗: {key}: {msg}")
                    failures.append((key, msg))

        # ---- 動画フェーズ ----
        if do_video:
            if not job.pptx.exists():
                print(f"✗ スライド(pptx)が見つかりません: {job.pptx}")
                return 1
            if not job.rec_parts:
                print(f"✗ 録画ファイルが見つかりません: {job.basename}_rec*.mp4")
                return 1
            # 台本・録画・ナレーション wav のいずれかが完成 mp4 より新しければ再合成する
            # （台本短縮→再TTS→再build のループで --force を要求しないため）
            video_inputs = [job.transcript_rec, *job.rec_parts,
                            *sorted(job.audio_dir.glob("*.wav"))]
            if job.out_mp4.exists() and not args.force \
                    and _is_fresh(job.out_mp4, video_inputs):
                print(f"= skip {job.out_mp4.name}（入力より新しい。--force で再生成）")
            else:
                print("\n▶ 録画を正規化")
                normalize_recording(job, force=args.force)
                print("▶ スライドをPNGへレンダリング")
                png_by_index = lm.render_pptx_to_png(job.pptx, job.png_dir,
                                                     scale=args.png_scale)
                print(f"  PNG {len(png_by_index)} ページ")
                print(f"▶ セグメント合成 → {job.out_mp4.name}")
                job.seg_dir.mkdir(parents=True, exist_ok=True)
                seg_files: list = []
                for n, s in enumerate(segs, 1):
                    out = job.seg_dir / f"seg_{n:03d}.mp4"
                    if isinstance(s, SlideSeg):
                        png = png_by_index.get(s.page)
                        if png is None:
                            print(f"  ! [{n:>3}] スライド{s.page} のPNGが無くスキップ")
                            continue
                        wav = job.audio_dir / f"slide_{s.page:02d}.wav"
                        if s.text and wav.exists():
                            lm._segment_with_audio(
                                png, wav, out,
                                lead_seconds=args.slide_lead_seconds,
                                tail_seconds=args.slide_tail_seconds)
                        else:
                            lm._segment_silent(png, args.default_still_seconds, out)
                        _ensure_stereo(out)
                        seg_files.append(out)
                        print(f"  [{n:>3}] スライド{s.page}")
                    else:  # RecSeg
                        wav = job.audio_dir / f"rec_{s.index:02d}.wav"
                        have = bool(s.text) and wav.exists()
                        try:
                            status, info = build_rec_segment(
                                job.rec_norm, s.start, s.end,
                                wav if have else None, out,
                                orig_volume=args.orig_volume,
                                rec_lead_seconds=args.rec_lead_seconds,
                                tolerance=args.tolerance)
                            seg_files.append(out)
                            tag = {"ok": "",
                                   "freeze": f" (フリーズ延長 +{info['freeze']:.1f}s)",
                                   "over": f" ⚠許容超過 (+{info['freeze']:.1f}s)"}[status]
                            print(f"  [{n:>3}] 録画{s.index} "
                                  f"[{_mmss(s.start)}-{_mmss(s.end)}]{tag}")
                            if status == "over":
                                over_list.append((s, info))
                        except subprocess.CalledProcessError as e:
                            tail = e.stderr if isinstance(e.stderr, str) else ""
                            last = tail.splitlines()[-1] if tail else str(e)
                            print(f"  ! [{n:>3}] 録画{s.index} 合成失敗: {last}")
                            failures.append((f"録画{s.index}", "ffmpeg失敗"))
                if not seg_files:
                    print("✗ セグメントが生成できませんでした。")
                    return 1
                _concat_segments(seg_files, job.out_mp4, job.work_dir)
                print(f"\n✓ 動画: {job.out_mp4}")

    # ---- レポート・終了コード ----
    rc = 0
    if failures:
        print(f"\n⚠ 失敗セグメント {len(failures)} 件:")
        for k, m in failures:
            print(f"   - {k}: {m}")
        rc = 1
    if over_list:
        print(f"\n⚠ 台本短縮が必要な録画セグメント {len(over_list)} 件"
              f"（許容 {args.tolerance:.0%} を超過。暫定でフリーズフレーム延長済み）:")
        for s, info in over_list:
            T = info["T"]
            req = info["required"]
            nb = char_budget(T, args.cps, args.fill_ratio)
            nc = _net_chars(s.text)
            print(f"   - 録画{s.index} [{_mmss(s.start)}-{_mmss(s.end)}] {s.label}: "
                  f"ナレーション {req:.1f}s > セグメント {T:.1f}s / "
                  f"文字 {nc} → {nb} 文字以下へ短縮")
        print("  → 該当セグメントの台本を短縮し、再度 build してください。")
        rc = 2
    if rc == 0:
        print("\n✓ 完了")
    return rc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _add_budget_opts(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--cps", type=float, default=CPS_EFFECTIVE,
                    help=f"日本語TTS実効速度 net文字/秒（既定 {CPS_EFFECTIVE}）")
    ap.add_argument("--fill-ratio", type=float, default=FILL_RATIO,
                    help=f"文字数バジェットの充填率（既定 {FILL_RATIO}）")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="practice_movie.py",
        description="実践レクチャーのPC録画にAI音声を付けて動画化する"
                    "（make-lecture-movie の関数を再利用）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # calibrate
    pc = sub.add_parser("calibrate",
                        help="座学成果物から日本語TTS実効速度(cps)を実測")
    pc.add_argument("--lectures-dir", default="lectures",
                    help="検索ルート（既定: カレント直下の lectures/）")
    pc.set_defaults(func=cmd_calibrate)

    # analyze
    pa = sub.add_parser("analyze",
                        help="録画を正規化→フレーム抽出し時刻対応表を出力")
    pa.add_argument("id", help="レクチャーID（例 L1-1-3）/グロブ/パス")
    pa.add_argument("--lectures-dir", default="lectures")
    pa.add_argument("--max-frames", type=int, default=FRAMES_MAX_DEFAULT,
                    help=f"抽出フレーム上限（既定 {FRAMES_MAX_DEFAULT}）")
    pa.add_argument("--frame-scale", type=_parse_frame_scale,
                    default=(FRAME_W, FRAME_H),
                    help=f"抽出フレームの解像度（既定 {FRAME_W}x{FRAME_H}）")
    pa.add_argument("--force", action="store_true",
                    help="rec_norm.mp4 を再生成する")
    pa.set_defaults(func=cmd_analyze)

    # transcript-check
    pt = sub.add_parser("transcript-check",
                        help="台本のタイムコード整合・文字数バジェットを検査")
    pt.add_argument("id", help="レクチャーID（例 L1-1-3）/グロブ/パス")
    pt.add_argument("--lectures-dir", default="lectures")
    _add_budget_opts(pt)
    pt.set_defaults(func=cmd_transcript_check)

    # build
    pb = sub.add_parser("build",
                        help="TTS→スライドPNG→セグメント合成→結合で動画を生成")
    pb.add_argument("id", help="レクチャーID（例 L1-1-3）/グロブ/パス")
    pb.add_argument("--lectures-dir", default="lectures")
    pb.add_argument("--audio-only", action="store_true", help="音声(wav)のみ生成")
    pb.add_argument("--video-only", action="store_true",
                    help="動画のみ生成（既存 wav が必要）")
    pb.add_argument("--force", action="store_true",
                    help="wav / rec_norm / mp4 を再生成")
    pb.add_argument("--orig-volume", type=float, default=ORIG_VOLUME_DEFAULT,
                    help=f"録画の元音声の音量（既定 {ORIG_VOLUME_DEFAULT}）")
    pb.add_argument("--tolerance", type=float, default=TOLERANCE_DEFAULT,
                    help=f"ナレーション超過の許容率（既定 {TOLERANCE_DEFAULT}）")
    pb.add_argument("--rec-lead-seconds", type=float, default=REC_LEAD_SECONDS_DEFAULT,
                    help=f"録画開始からナレーション開始までの秒（既定 {REC_LEAD_SECONDS_DEFAULT}）")
    _add_budget_opts(pb)
    # TTS / スライド関連（lm の既定に合わせる）
    pb.add_argument("--model", default="gemini-3.1-flash-tts-preview",
                    help="TTSモデル名（安定版は gemini-2.5-pro-tts）")
    pb.add_argument("--voice", default=None,
                    help="声名（既定は指示ファイルのVoice、無ければ Callirrhoe）")
    pb.add_argument("--language-code", default="ja-JP")
    pb.add_argument("--instruction", default=None,
                    help="スタイル指示ファイル（既定: <repo>/vertexai-tts-instruction.md）")
    pb.add_argument("--max-chunk-chars", type=int, default=250,
                    help="TTS分割の文字数上限（2分バグ回避）")
    pb.add_argument("--chunk-gap-seconds", type=float, default=lm.CHUNK_GAP_SECONDS,
                    help="分割TTSチャンク間の無音秒数")
    pb.add_argument("--slide-lead-seconds", type=float, default=lm.SLIDE_LEAD_SECONDS,
                    help="スライド表示からナレーション開始までの無音秒数")
    pb.add_argument("--slide-tail-seconds", type=float, default=lm.SLIDE_TAIL_SECONDS,
                    help="スライドのナレーション終了から次までの無音秒数")
    pb.add_argument("--default-still-seconds", type=float, default=4.0,
                    help="台本の無いスライドの表示秒数")
    pb.add_argument("--png-scale", type=int, default=lm.PNG_SCALE,
                    help="pptx→PNG のスケール倍率（既定2で1920x1080相当）")
    pb.set_defaults(func=cmd_build)

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
