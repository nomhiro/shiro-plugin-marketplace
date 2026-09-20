#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台本(*_transcript.md)とPowerPointスライド(*.pptx)からAI音声付き講座動画を生成する。

動画講座向け。Marp ベースの先行実装を土台に、
入力スライドを Marp markdown → PowerPoint(.pptx) に、レクチャー単位を
「1デック＝1レクチャー（basename ペア）」に移植したもの。

パイプライン:
  1. レクチャーID/グロブ/パスから (pptx, transcript) ペアを basename で解決
  2. 台本mdを `## スライドN:` 単位にパース（ページNと1:1対応）
  3. Google Cloud Text-to-Speech (Gemini-TTS) で各スライドのナレーションを合成
     - flash-tts の「2分以上で読み上げが速くなる」バグ回避のため台本を細分割して結合
  4. LibreOffice(soffice) で pptx → PDF → PNG（PyMuPDF）にレンダリング
  5. ffmpeg で「スライド画像＋音声」をレクチャー単位のMP4に合成

出力:
  <section>/<basename>_audio/speech_NN.wav
  <section>/<basename>.mp4
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Windows既定(cp932)だと ▶ ✓ 等で UnicodeEncodeError になり TTS開始前に落ちるため UTF-8 化
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------------------
# 外部コマンドの解決
# ---------------------------------------------------------------------------
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

# Gemini-TTS の出力フォーマット（LINEAR16 = 24kHz / mono / 16bit）
TTS_SAMPLE_RATE = 24000
# 既定の「間」（秒）。CLIオプションで上書き可能。
CHUNK_GAP_SECONDS = 0.5      # スライド内：分割したTTSチャンク間の無音
SLIDE_LEAD_SECONDS = 1.0     # スライド表示からナレーション開始までの無音
SLIDE_TAIL_SECONDS = 2.0     # ナレーション終了から次スライドまでの無音
# → スライド間の実質的な「間」≒ 前スライドのtail + 次スライドのlead（既定で約3秒）
# 動画の解像度・フレームレート
VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS = 1920, 1080, 30
# pptx→PNG のスケール（PDF 72dpi × 倍率）。16:9 デック(960x540pt)×2 = 1920x1080
PNG_SCALE = 2


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    """サブプロセスを実行する（失敗時は例外）。"""
    printable = " ".join(str(c) for c in cmd)
    print(f"  $ {printable[:300]}")
    return subprocess.run(cmd, check=True, **kwargs)


# ---------------------------------------------------------------------------
# 入力解決（レクチャーID/グロブ/パス → (pptx, transcript) ペア）
# ---------------------------------------------------------------------------
@dataclass
class Job:
    basename: str            # 例 "L1-1-2_座学_model-selection"
    section_dir: Path        # 例 .../lectures/01_plan_manage
    pptx: Path
    transcript: Path
    audio_dir: Path
    out_mp4: Path
    repo_root: Path


def find_repo_root(start: Path) -> Path:
    """`lectures` ディレクトリの親をリポジトリルートとして返す。"""
    for parent in [start, *start.parents]:
        if parent.name == "lectures":
            return parent.parent
    return start.parent


def _spec_to_glob(spec: str) -> str:
    """レクチャーID/グロブを transcript のグロブパターンへ変換する。

    例: "L1-1-x" → "L1-1-*_transcript.md" / "L1-1-2" → "L1-1-2*_transcript.md"
    """
    s = spec.strip()
    s = re.sub(r"-[xX*]$", "-*", s)   # 末尾の -x / -X / -* を -* に正規化
    if "*" not in s:
        s = s + "*"                    # 前方一致（L1-1-2 → L1-1-2*）
    return s + "_transcript.md"


def _job_from_transcript(transcript: Path) -> Job:
    name = transcript.name
    if not name.endswith("_transcript.md"):
        sys.exit(f"transcript ファイル名が *_transcript.md ではありません: {transcript}")
    basename = name[: -len("_transcript.md")]
    section_dir = transcript.parent
    return Job(
        basename=basename,
        section_dir=section_dir,
        pptx=section_dir / f"{basename}.pptx",
        transcript=transcript,
        audio_dir=section_dir / f"{basename}_audio",
        out_mp4=section_dir / f"{basename}.mp4",
        repo_root=find_repo_root(section_dir),
    )


def is_practice(basename: str) -> bool:
    """実践（ハンズオン）レクチャーか。命名 `L?-?-?_実践_*` で判定。"""
    return bool(re.search(r"_実践(?:_|$)", basename))


def resolve_jobs(specs: list[str], lectures_dir: Path) -> list[Job]:
    """指定子の配列を (pptx, transcript) ペアのジョブ配列へ解決する。"""
    found: dict[Path, Job] = {}
    for spec in specs:
        p = Path(spec)
        # 既存パス指定（.pptx か _transcript.md）
        if p.exists() and p.is_file():
            if p.name.endswith("_transcript.md"):
                job = _job_from_transcript(p.resolve())
            elif p.suffix.lower() == ".pptx":
                t = p.with_name(p.stem + "_transcript.md")
                if not t.exists():
                    sys.exit(f"対応する台本が見つかりません: {t}")
                job = _job_from_transcript(t.resolve())
            else:
                sys.exit(f"未対応の入力です（.pptx か *_transcript.md を指定）: {p}")
            found[job.transcript] = job
            continue
        # ID / グロブ指定 → lectures 配下を再帰検索
        pattern = _spec_to_glob(spec)
        matches = sorted(lectures_dir.glob(f"**/{pattern}"))
        if not matches:
            sys.exit(f"'{spec}' に一致する *_transcript.md が {lectures_dir} 配下に見つかりません "
                     f"（検索パターン: {pattern}）。")
        for t in matches:
            job = _job_from_transcript(t.resolve())
            found[job.transcript] = job
    return list(found.values())


# ---------------------------------------------------------------------------
# パース
# ---------------------------------------------------------------------------
def parse_transcript(transcript_md: Path) -> dict[int, str]:
    """台本mdを {スライド番号: 本文} にパースする。`## スライドN:` 見出しで分割。"""
    text = transcript_md.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^##\s*スライド\s*(\d+)\s*[:：].*$", text)
    result: dict[int, str] = {}
    for i in range(1, len(parts) - 1, 2):
        num = int(parts[i])
        raw = parts[i + 1]
        raw = re.sub(r"(?m)^---\s*$", "", raw)  # セグメント区切りを除去
        body = raw.strip()
        if body:
            result[num] = body
    return result


def count_slides(pptx: Path) -> int:
    """pptx のスライド枚数を返す（PNG化前のセグメント計画に使用）。"""
    try:
        from pptx import Presentation
    except ImportError:
        sys.exit("python-pptx が未インストールです。"
                 "`pip install -r scripts/requirements.txt` を実行してください。")
    return len(Presentation(str(pptx)).slides)


# ---------------------------------------------------------------------------
# セグメント計画（音声・動画で共通の採番ルール）
# ---------------------------------------------------------------------------
@dataclass
class Segment:
    page_index: int
    speech_name: str | None  # 音声がある場合 "speech_NN.wav"、無ければ None
    text: str | None


def plan_segments(num_pages: int, transcript: dict[int, str]) -> list[Segment]:
    """1..num_pages を順に走査し、台本があるページに speech_NN を採番する。"""
    segments: list[Segment] = []
    seq = 0
    for idx in range(1, num_pages + 1):
        body = transcript.get(idx)
        if body:
            seq += 1
            segments.append(Segment(idx, f"speech_{seq:02d}.wav", body))
        else:
            segments.append(Segment(idx, None, None))
    return segments


# ---------------------------------------------------------------------------
# TTS（slide-movie から流用）
# ---------------------------------------------------------------------------
def chunk_text_for_tts(text: str, max_chars: int = 250) -> list[str]:
    """台本本文をTTS用の短いチャンクに分割する。

    flash-tts は約2分以上の音声を一度に生成すると読み上げ速度が速くなるバグが
    あるため、文（。！？）単位に分割し、各チャンクが概ね max_chars 文字以内に
    収まるようにまとめる（保守的に2分未満を狙う）。
    """
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n+", "", text)          # 改行（文区切り・段落区切り）を結合
    text = re.sub(r"[ \t　]+", " ", text).strip()
    if not text:
        return []
    sentences = re.findall(r"[^。！？]*[。！？]", text)
    consumed = "".join(sentences)
    if len(consumed) < len(text):
        sentences.append(text[len(consumed):])
    sentences = [s for s in sentences if s.strip()]

    chunks: list[str] = []
    cur = ""
    for s in sentences:
        if cur and len(cur) + len(s) > max_chars:
            chunks.append(cur)
            cur = s
        else:
            cur += s
    if cur:
        chunks.append(cur)
    return chunks or [text]


_tts_client = None


def get_tts_client():
    global _tts_client
    if _tts_client is None:
        try:
            from google.cloud import texttospeech
        except ImportError:
            sys.exit("google-cloud-texttospeech が未インストールです。"
                     "`pip install -r scripts/requirements.txt` を実行してください。")
        try:
            _tts_client = texttospeech.TextToSpeechClient()
        except Exception as e:  # 認証エラーなど
            sys.exit(f"Text-to-Speech クライアントの初期化に失敗しました: {e}\n"
                     "`gcloud auth application-default login` と "
                     "Text-to-Speech / Vertex AI(aiplatform) API の有効化を確認してください。")
    return _tts_client


def _make_silence_wav(path: Path, seconds: float) -> None:
    run([FFMPEG, "-y", "-f", "lavfi", "-i",
         f"anullsrc=channel_layout=mono:sample_rate={TTS_SAMPLE_RATE}",
         "-t", f"{seconds}", "-c:a", "pcm_s16le", str(path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _tts_call(client, chunk: str, prompt: str, voice: str, model: str,
              language_code: str) -> bytes:
    from google.cloud import texttospeech
    resp = client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=chunk, prompt=(prompt or None)),
        voice=texttospeech.VoiceSelectionParams(
            language_code=language_code, name=voice, model_name=model),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16),
    )
    return resp.audio_content


def synthesize_chunk_with_retry(client, chunk: str, style_prompt: str, voice: str,
                                model: str, language_code: str) -> bytes:
    """1チャンクを合成する。安全フィルタ誤検知や一時障害に対してリトライする。"""
    import time
    from google.api_core import exceptions as gexc

    attempts = [(style_prompt, None), (style_prompt, "同条件で再試行")]
    if style_prompt:
        attempts.append(("", "スタイル指示なしで再試行"))

    last_err: Exception | None = None
    for prompt_val, note in attempts:
        try:
            data = _tts_call(client, chunk, prompt_val, voice, model, language_code)
            if note:
                print(f"      → {note}: 成功")
            return data
        except gexc.InvalidArgument as e:
            last_err = e
            if note is None:
                print("      ! 安全フィルタ等に拒否されました。再試行します")
            continue
        except (gexc.ServiceUnavailable, gexc.DeadlineExceeded,
                gexc.ResourceExhausted) as e:
            last_err = e
            time.sleep(2)
            continue
    raise last_err


def synthesize_speech_file(text: str, style_prompt: str, voice: str, model: str,
                           language_code: str, out_wav: Path, tmp_dir: Path,
                           max_chars: int, chunk_gap: float = CHUNK_GAP_SECONDS) -> None:
    """1スライド分の台本をTTSで合成し out_wav に書き出す（必要に応じ細分割→結合）。"""
    client = get_tts_client()
    chunks = chunk_text_for_tts(text, max_chars=max_chars)

    chunk_wavs: list[Path] = []
    for i, chunk in enumerate(chunks, 1):
        data = synthesize_chunk_with_retry(
            client, chunk, style_prompt, voice, model, language_code)
        cw = tmp_dir / f"{out_wav.stem}_chunk_{i:03d}.wav"
        cw.write_bytes(data)
        chunk_wavs.append(cw)

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if len(chunk_wavs) == 1:
        shutil.copyfile(chunk_wavs[0], out_wav)
    else:
        silence = tmp_dir / f"chunk_gap_{chunk_gap}.wav"
        if not silence.exists():
            _make_silence_wav(silence, chunk_gap)
        listfile = tmp_dir / f"{out_wav.stem}_concat.txt"
        lines = []
        for i, cw in enumerate(chunk_wavs):
            if i > 0:
                lines.append(f"file '{str(silence).replace(chr(92), '/')}'")
            lines.append(f"file '{str(cw).replace(chr(92), '/')}'")
        listfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
        run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
             "-ar", str(TTS_SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load_voice_and_style(instruction_path: Path, default_voice: str) -> tuple[str, str]:
    """vertexai-tts-instruction.md から声名とスタイルプロンプトを抽出する。"""
    if not instruction_path.exists():
        return default_voice, ""
    text = instruction_path.read_text(encoding="utf-8")
    vm = re.search(r"Voice\s*[：:]\s*([A-Za-z]+)", text)
    voice = vm.group(1) if vm else default_voice
    style = re.sub(r"(?m)^\s*Voice\s*[：:].*$", "", text)
    style = re.sub(r"(?m)^\s*---\s*$", "", style).strip()
    return voice, style


# ---------------------------------------------------------------------------
# スライド → PNG（LibreOffice soffice で pptx→PDF→PNG）
# ---------------------------------------------------------------------------
def find_soffice() -> str | None:
    for p in (r"C:/Program Files/LibreOffice/program/soffice.com",
              r"C:/Program Files (x86)/LibreOffice/program/soffice.com",
              r"C:/Program Files/LibreOffice/program/soffice.exe"):
        if os.path.exists(p):
            return p
    return shutil.which("soffice")


def kill_soffice() -> None:
    """常駐 soffice を終了（変換の横取り防止）。失敗は無視。"""
    if os.name == "nt":
        for img in ("soffice.bin", "soffice.exe"):
            subprocess.run(["taskkill", "/IM", img, "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _pptx_to_pdf(soffice: str, pptx: Path, workdir: Path) -> Path | None:
    """ASCII作業コピー経由で pptx→PDF。生成PDFパスを返す（失敗時 None）。"""
    workdir.mkdir(parents=True, exist_ok=True)
    safe = workdir / "src.pptx"
    shutil.copyfile(pptx, safe)
    pdf = workdir / "src.pdf"
    if pdf.exists():
        pdf.unlink()
    subprocess.run([soffice, "--headless", "--norestore", "--convert-to", "pdf",
                    "--outdir", str(workdir), str(safe)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return pdf if pdf.exists() else None


def render_pptx_to_png(pptx: Path, out_dir: Path, scale: int = PNG_SCALE) -> dict[int, Path]:
    """pptx を soffice で PDF 化し、PyMuPDF で各ページ PNG 化。{ページ番号: png} を返す。"""
    soffice = find_soffice()
    if not soffice:
        sys.exit("soffice (LibreOffice) が見つかりません。LibreOffice をインストールしてください。")
    lock = pptx.with_name("~$" + pptx.name)
    if lock.exists():
        print(f"    ! PowerPoint ロックあり（閉じてください）: {lock}")
    out_dir.mkdir(parents=True, exist_ok=True)
    kill_soffice()
    pdf = _pptx_to_pdf(soffice, pptx, out_dir)
    if not pdf:  # 横取り等で空振りした場合は一度だけ再試行
        kill_soffice()
        pdf = _pptx_to_pdf(soffice, pptx, out_dir)
    if not pdf:
        sys.exit(f"soffice が PDF を生成できませんでした（PowerPointで開いていないか確認）: {pptx}")

    import fitz
    doc = fitz.open(str(pdf))
    mapping: dict[int, Path] = {}
    for i, pg in enumerate(doc, 1):
        out = out_dir / f"page_{i:02d}.png"
        pg.get_pixmap(matrix=fitz.Matrix(scale, scale)).save(str(out))
        mapping[i] = out
    doc.close()
    return mapping


# ---------------------------------------------------------------------------
# 動画合成（slide-movie から流用）
# ---------------------------------------------------------------------------
_VF = f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease," \
      f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1"


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
        capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _segment_with_audio(png: Path, wav: Path, out: Path,
                        lead_seconds: float = 0.0, tail_seconds: float = 0.0) -> None:
    """スライド画像＋音声のセグメントを作る（先頭/末尾に無音を付与）。"""
    dur = _probe_duration(wav)
    total = lead_seconds + dur + tail_seconds
    afilters = []
    if lead_seconds > 0:
        afilters.append(f"adelay={int(lead_seconds * 1000)}:all=1")
    afilters.append("apad")
    run([FFMPEG, "-y", "-loop", "1", "-i", str(png), "-i", str(wav),
         "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
         "-vf", _VF, "-r", str(VIDEO_FPS),
         "-af", ",".join(afilters), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _segment_silent(png: Path, seconds: float, out: Path) -> None:
    run([FFMPEG, "-y", "-loop", "1", "-i", str(png),
         "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
         "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
         "-vf", _VF, "-r", str(VIDEO_FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-t", f"{seconds}", "-movflags", "+faststart", str(out)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_lecture_video(segments: list[Segment], png_by_index: dict[int, Path],
                        audio_dir: Path, out_mp4: Path, tmp_dir: Path,
                        default_still_seconds: float,
                        lead_seconds: float = SLIDE_LEAD_SECONDS,
                        tail_seconds: float = SLIDE_TAIL_SECONDS) -> None:
    """セグメントからMP4を合成する。"""
    seg_files: list[Path] = []
    for n, seg in enumerate(segments, 1):
        png = png_by_index.get(seg.page_index)
        if png is None:
            print(f"    ! ページ{seg.page_index} のPNGが見つからずスキップ")
            continue
        seg_out = tmp_dir / f"seg_{n:03d}.mp4"
        wav = audio_dir / seg.speech_name if seg.speech_name else None
        if wav and wav.exists():
            _segment_with_audio(png, wav, seg_out,
                                lead_seconds=lead_seconds, tail_seconds=tail_seconds)
        else:
            _segment_silent(png, default_still_seconds, seg_out)
        seg_files.append(seg_out)

    if not seg_files:
        print("    ! セグメントが無いため動画生成をスキップ")
        return

    listfile = tmp_dir / "segments.txt"
    listfile.write_text(
        "\n".join(f"file '{str(s).replace(chr(92), '/')}'" for s in seg_files) + "\n",
        encoding="utf-8")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    try:
        run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
             "-c", "copy", "-movflags", "+faststart", str(out_mp4)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(VIDEO_FPS),
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-movflags", "+faststart", str(out_mp4)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="台本(*_transcript.md)とPowerPoint(*.pptx)からAI音声付き講座動画を生成")
    ap.add_argument("targets", nargs="+",
                    help="レクチャーID（L1-1-2）/グロブ（L1-1-x）/ .pptx か *_transcript.md のパス")
    ap.add_argument("--lectures-dir", default="lectures",
                    help="検索ルート（既定: カレント直下の lectures/）")
    ap.add_argument("--include-practice", action="store_true",
                    help="実践（ハンズオン）レクチャーも生成する（既定はスキップ。実践は自分の声で収録するため）")
    ap.add_argument("--audio-only", action="store_true", help="音声(wav)のみ生成")
    ap.add_argument("--video-only", action="store_true", help="動画(mp4)のみ生成")
    ap.add_argument("--model", default="gemini-3.1-flash-tts-preview",
                    help="TTSモデル名（既定=最新flash。高音質安定版は gemini-2.5-pro-tts）")
    ap.add_argument("--voice", default=None,
                    help="声名（既定は指示ファイルのVoice、無ければ Callirrhoe）")
    ap.add_argument("--language-code", default="ja-JP")
    ap.add_argument("--instruction", default=None,
                    help="スタイル指示ファイル（既定: <repo>/vertexai-tts-instruction.md）")
    ap.add_argument("--force", action="store_true", help="既存のwav/mp4も再生成")
    ap.add_argument("--default-still-seconds", type=float, default=4.0,
                    help="台本が無いスライドの表示秒数")
    ap.add_argument("--max-chunk-chars", type=int, default=250,
                    help="TTS分割の文字数上限（2分バグ回避）")
    ap.add_argument("--chunk-gap-seconds", type=float, default=CHUNK_GAP_SECONDS,
                    help="スライド内：分割TTSチャンク間の無音秒数")
    ap.add_argument("--slide-lead-seconds", type=float, default=SLIDE_LEAD_SECONDS,
                    help="スライド表示からナレーション開始までの無音秒数")
    ap.add_argument("--slide-tail-seconds", type=float, default=SLIDE_TAIL_SECONDS,
                    help="ナレーション終了から次スライドまでの無音秒数")
    ap.add_argument("--png-scale", type=int, default=PNG_SCALE,
                    help="pptx→PNG のスケール倍率（既定2で1920x1080相当）")
    ap.add_argument("--dry-run", action="store_true",
                    help="TTS/soffice/ffmpegを実行せず、分割計画のみ表示")
    args = ap.parse_args()

    lectures_dir = Path(args.lectures_dir).resolve()
    jobs = resolve_jobs(args.targets, lectures_dir)
    if not jobs:
        sys.exit("対象レクチャーが解決できませんでした。")

    # 実践（ハンズオン）は既定でスキップ（受講者＝制作者が自分の声で収録するため）
    practice = [j for j in jobs if is_practice(j.basename)]
    if practice and not args.include_practice:
        print("⏭ 実践（ハンズオン）はスキップします（自分の声で収録するため）:")
        for j in practice:
            print(f"   - {j.basename}")
        print("   （実践も音声/動画化したい場合のみ --include-practice）")
        jobs = [j for j in jobs if not is_practice(j.basename)]
    if not jobs:
        sys.exit("対象（座学）レクチャーがありません。"
                 "実践のみを指定した場合は、必要なら --include-practice を付けてください。")

    voice_default = "Callirrhoe"
    do_audio = not args.video_only
    do_video = not args.audio_only

    print(f"■ 対象レクチャー: {len(jobs)} 件")
    for job in jobs:
        print(f"  - {job.basename}")
        if not job.transcript.exists():
            sys.exit(f"台本が見つかりません: {job.transcript}")
        if do_video and not job.pptx.exists():
            sys.exit(f"スライド(pptx)が見つかりません: {job.pptx}")

    for job in jobs:
        print(f"\n=== {job.basename} ===")
        transcript = parse_transcript(job.transcript)
        # ページ総数: pptxがあれば枚数、無ければ台本の最大スライド番号
        if job.pptx.exists():
            num_pages = max(count_slides(job.pptx), max(transcript, default=0))
        else:
            num_pages = max(transcript, default=0)
        segments = plan_segments(num_pages, transcript)
        print(f"  ページ数={num_pages} / 台本セグメント数={len(transcript)}")

        instruction_path = Path(args.instruction) if args.instruction \
            else job.repo_root / "vertexai-tts-instruction.md"
        voice, style_prompt = load_voice_and_style(instruction_path, default_voice=voice_default)
        if args.voice:
            voice = args.voice

        if args.dry_run:
            print(f"  [dry-run] voice={voice} / style={len(style_prompt)}文字 / "
                  f"model={args.model} / max_chunk_chars={args.max_chunk_chars}")
            for seg in segments:
                if seg.text:
                    n_chunks = len(chunk_text_for_tts(seg.text, args.max_chunk_chars))
                    print(f"    スライド{seg.page_index:>2} → {seg.speech_name} "
                          f"（{len(seg.text)}文字 / {n_chunks}チャンク）")
                else:
                    print(f"    スライド{seg.page_index:>2} → 台本なし（{args.default_still_seconds}秒静止）")
            continue

        with tempfile.TemporaryDirectory(prefix="lecture_movie_") as td:
            tmp = Path(td)
            failed: list[tuple[str, int, str]] = []

            # ---- 音声フェーズ ----
            if do_audio:
                print(f"▶ 音声生成 (model={args.model}, voice={voice})")
                for seg in segments:
                    if not seg.text:
                        continue
                    out_wav = job.audio_dir / seg.speech_name
                    if out_wav.exists() and not args.force:
                        print(f"  = skip {seg.speech_name}（既存）")
                        continue
                    print(f"  + {seg.speech_name}（スライド{seg.page_index}）")
                    try:
                        synthesize_speech_file(
                            text=seg.text, style_prompt=style_prompt, voice=voice,
                            model=args.model, language_code=args.language_code,
                            out_wav=out_wav, tmp_dir=tmp, max_chars=args.max_chunk_chars,
                            chunk_gap=args.chunk_gap_seconds)
                    except Exception as e:  # 1セグメントの失敗で全体を止めない
                        msg = str(e).splitlines()[0][:160]
                        print(f"    ! 失敗: {seg.speech_name}（スライド{seg.page_index}）: {msg}")
                        failed.append((seg.speech_name, seg.page_index, msg))

            # ---- 動画フェーズ ----
            if do_video:
                if job.out_mp4.exists() and not args.force:
                    print(f"= skip {job.out_mp4.name}（既存）")
                else:
                    print("▶ スライドをPNGへレンダリング")
                    png_by_index = render_pptx_to_png(job.pptx, tmp / "png", scale=args.png_scale)
                    print(f"  PNG {len(png_by_index)} ページ生成")
                    print(f"▶ 動画合成 → {job.out_mp4.name}")
                    seg_tmp = tmp / "vid"
                    seg_tmp.mkdir(parents=True, exist_ok=True)
                    build_lecture_video(
                        segments=segments, png_by_index=png_by_index,
                        audio_dir=job.audio_dir, out_mp4=job.out_mp4, tmp_dir=seg_tmp,
                        default_still_seconds=args.default_still_seconds,
                        lead_seconds=args.slide_lead_seconds,
                        tail_seconds=args.slide_tail_seconds)

            if failed:
                print(f"  ⚠ 失敗セグメント {len(failed)} 件（動画では無音静止になります）:")
                for name, page, msg in failed:
                    print(f"     - {name}（スライド{page}）: {msg}")
                print("    対処: 再実行（誤検知は時間を置くと通る場合あり）、台本の言い回し変更、"
                      "または --model gemini-2.5-pro-tts を試す。")

    print("\n✓ 完了")


if __name__ == "__main__":
    main()
