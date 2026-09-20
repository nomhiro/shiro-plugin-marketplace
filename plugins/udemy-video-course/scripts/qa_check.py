# -*- coding: utf-8 -*-
"""完成した動画の品質ゲートを1コマンドで通す。

`build` のあとに毎回これを走らせる。人手で確認すると必ず抜ける4つを機械で見る:

1. **TTS の異常**  合成音声は、まれに同じ文を繰り返したり（ループ）、途中で切れたり
   する。原稿の文字数から期待尺を出し、実尺との比で外れ値を落とす。
2. **沈黙率**      区間の尺に対してナレーションが短すぎると「間が持たない」動画になる。
   逆に 5% を切ると喋りっぱなしで視聴者の目が追いつかない。
3. **体言止め**    名詞で終わる文は TTS でぶつ切りに聞こえる。述語で言い切らせる。
4. **管理番号**    レクチャー番号や試験コードをナレーションに出さない（受講者には
   意味のない内部識別子）。

使い方:
    python qa_check.py <...>_transcript_rec.md
    python qa_check.py <...>_transcript_rec.md --cps 5.7 --strict
    python qa_check.py <...>_transcript_rec.md --silence-range 8,25
    python qa_check.py <...>_transcript_rec.md --no-style      # 文体チェックを外す

終了コード: --strict のとき、1件でも指摘があれば 1。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 合成音声の実効文字/秒。各講座で calibrate して上書きする
DEFAULT_CPS = 5.7
# wav実尺 / 期待尺。この外はループ・途切れを疑う
LOOP_RATIO, CUT_RATIO = 1.8, 0.62
# 1秒あたりの文字数。この帯を外れると読み上げが異常に速い/遅い
CPS_BAND = (3.0, 8.5)

SLIDE_RE = re.compile(r"^スライド\s*(\d+)\s*[:：]")
REC_RE = re.compile(
    r"^録画\s*(\d+)\s*\[(?:(\d+):)?(\d+):([\d.]+)\s*-\s*(?:(\d+):)?(\d+):([\d.]+)\]\s*[:：]")

# 体言止めの判定。動詞・形容詞を列挙するのは無理なので、文末の1文字で見る。
#   日本語の述語は、終止形が「う段のかな」（呼ぶ・投げる・出す…）、
#   形容詞が「い」、過去が「た/だ」、否定が「ん」で終わる。
#   一方で名詞は漢字・カタカナ・それ以外のかなで終わる（要否・ツール・こと…）。
# 文末の終助詞（ね・よ・な・か…）は先に落としてから判定する。
SENTENCE_PARTICLES = "ねよなさわぞぜっ"
CLOSERS = "」』）)】”’\"'"
# う段のかな（終止形）＋い（形容詞）＋た/だ（過去）＋ん（否定・のだ）
PREDICATE_LAST = set("うくぐすずつづぬふぶむゆるいただんか")  # か＝疑問文


def is_taigendome(core: str) -> bool:
    """名詞で終わっていれば True（＝直すべき）。"""
    s = core.rstrip(CLOSERS)
    while s and s[-1] in SENTENCE_PARTICLES:
        s = s[:-1]
    if not s:
        return False
    return s[-1] not in PREDICATE_LAST


DEFAULT_ID_PATTERN = r"[A-Z]\d+-\d+(?:-\d+)?|[A-Z]\d+\.[a-z]-\d+"


def ffprobe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except Exception:
        return None


def parse_transcript(path: Path):
    """台本を「スライド」「録画」の区間に割る。見出しの順＝再生順。"""
    segments = []
    head, body = None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if head is not None:
                segments.append((head, "\n".join(body).strip()))
            head, body = line[3:].strip(), []
        elif head is not None:
            body.append(line)
    if head is not None:
        segments.append((head, "\n".join(body).strip()))

    out = []
    rec_i = 0
    for head, text in segments:
        m = SLIDE_RE.match(head)
        if m:
            out.append({"kind": "slide", "n": int(m.group(1)), "head": head, "text": text})
            continue
        m = REC_RE.match(head)
        if m:
            rec_i += 1
            def sec(h, mi, s):
                return (int(h) if h else 0) * 3600 + int(mi) * 60 + float(s)
            start = sec(m.group(2), m.group(3), m.group(4))
            end = sec(m.group(5), m.group(6), m.group(7))
            out.append({"kind": "rec", "n": rec_i, "head": head, "text": text,
                        "span": end - start})
    return out


def audio_path(audio_dir: Path, seg) -> Path:
    if seg["kind"] == "slide":
        return audio_dir / f"slide_{seg['n']:02d}.wav"
    return audio_dir / f"rec_{seg['n']:02d}.wav"


def check_tts(segs, audio_dir: Path, cps: float):
    findings, rec_span, rec_narr = [], 0.0, 0.0
    for seg in segs:
        wav = audio_path(audio_dir, seg)
        if not wav.exists():
            findings.append((seg["head"], "音声ファイルが無い: " + wav.name))
            continue
        d = ffprobe_duration(wav)
        if d is None:
            findings.append((seg["head"], "尺を取得できない: " + wav.name))
            continue
        expected = len(seg["text"]) / cps
        ratio = d / expected if expected else 0.0
        chars_per_sec = len(seg["text"]) / d if d else 0.0
        if ratio > LOOP_RATIO:
            findings.append((seg["head"], f"ループ疑い（実尺/期待尺={ratio:.2f}）"))
        elif ratio < CUT_RATIO:
            findings.append((seg["head"], f"途切れ疑い（実尺/期待尺={ratio:.2f}）"))
        elif not (CPS_BAND[0] <= chars_per_sec <= CPS_BAND[1]):
            findings.append((seg["head"], f"読み上げ速度が帯の外（{chars_per_sec:.1f}字/秒）"))
        if seg["kind"] == "rec":
            rec_span += seg["span"]
            rec_narr += d
    silence = (rec_span - rec_narr) / rec_span * 100 if rec_span else 0.0
    return findings, silence, rec_span, rec_narr


def check_style(segs, id_pattern: str):
    findings = []
    id_re = re.compile(id_pattern)
    for seg in segs:
        for sentence in re.findall(r"[^。！？\n]{3,120}。", seg["text"]):
            core = sentence[:-1]
            if is_taigendome(core):
                findings.append((seg["head"], "体言止め: …" + core[-28:] + "。"))
        for hit in set(id_re.findall(seg["text"])):
            findings.append((seg["head"], f"管理番号の読み上げ: {hit}"))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--cps", type=float, default=DEFAULT_CPS)
    ap.add_argument("--audio-dir", type=Path, default=None)
    ap.add_argument("--silence-range", default="8,25",
                    help="録画パートの沈黙率の許容帯（%%）。既定 8,25")
    ap.add_argument("--id-pattern", default=DEFAULT_ID_PATTERN)
    ap.add_argument("--no-style", action="store_true")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    t = a.transcript
    if not t.exists():
        print(f"台本が見つかりません: {t}", file=sys.stderr)
        return 2
    base = t.name.replace("_transcript_rec.md", "")
    audio_dir = a.audio_dir or (t.parent / f"{base}_audio_rec")

    segs = parse_transcript(t)
    recs = [s for s in segs if s["kind"] == "rec"]
    slides = [s for s in segs if s["kind"] == "slide"]
    print(f"■ qa-check: {base}")
    print(f"  セグメント: スライド {len(slides)} / 録画 {len(recs)}")

    tts, silence, span, narr = check_tts(segs, audio_dir, a.cps)
    lo, hi = (float(x) for x in a.silence_range.split(","))
    print(f"  録画パート {span:.0f}s / ナレーション {narr:.0f}s / 沈黙 {silence:.1f}%")

    style = [] if a.no_style else check_style(segs, a.id_pattern)

    problems = list(tts) + list(style)
    if not (lo <= silence <= hi) and span:
        problems.append(("(全体)", f"沈黙率が帯の外: {silence:.1f}%（許容 {lo}〜{hi}%）"))

    if problems:
        print(f"\n  ⚠ 指摘 {len(problems)} 件")
        for head, msg in problems:
            print(f"   - [{head}] {msg}")
    else:
        print("\n  ✓ 問題なし")

    if a.json:
        a.json.write_text(json.dumps(
            {"base": base, "silence_pct": silence, "rec_span_sec": span,
             "narration_sec": narr,
             "problems": [{"segment": h, "message": m} for h, m in problems]},
            ensure_ascii=False, indent=2), encoding="utf-8")

    return 1 if (a.strict and problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
