"""`SCRIPT.md` の台詞を Gemini-TTS で音声化し、`audio_meta.json` を書く。

## なぜ Google の Gemini-TTS か

当初はオフラインの Kokoro（`jf_alpha`）を使い、**漢字が読めない**ため
`kana.py` でかな化して渡していた（実測 漢字 0.9字/秒で崩れる）。

Gemini-TTS は**漢字をそのまま読む**（実測 5.26字/秒・56行）。

**したがって TTS 用のかな化はもう不要。** `kana.py` は
読みの点検（`--check`）にだけ残す。`SCRIPT.tts.md` は生成しない。

自然言語で演技を指示できる機能（`SynthesisInput.prompt`）もあるが、
**既定では使わない。** content filter の誤検知が不規則に出て、
どの行に演技指示が乗るか予測できないため（詳細は下の `synthesize` の注記）。
「各文の後に一呼吸の間」は**台本の読点と行末の無音**で決定的に作る。

## 尺の真実はここで決まる

出力した `audio_meta.json` の `voices[].duration_s` が**実尺**。
これを `audio.mjs sync-durations` が `STORYBOARD.md` の `duration:` に書き戻し、
`assemble-index` がタイムラインを組む。**HTML に秒数を手書きしない。**

## flash-tts の既知のバグへの対処

`gemini-3.1-flash-tts-preview` は**約2分を超える音声を一度に生成すると
読み上げ速度が速くなる**。句点単位で約250文字に分割し、0.5秒の無音をはさんで
連結する（lecture_movie.py の実装と同じ）。1ユニットの1行は50〜80文字なので
通常は分割されない。

## 使い方

    # 認証（初回のみ。ユーザー自身が実行する）
    gcloud auth application-default login

    python tts.py <unit>                 # ユニットの名前か、videos/<unit> のパス
    python tts.py <unit> --only 4,5      # 台本を直した行だけ作り直す
    python tts.py <unit> --dry-run       # 何を投げるか確認するだけ（TTS に渡す文字列も出す）

話者・モデル・指示書・読みの辞書の場所は `course.yaml` の tts（course_config.py）。
作った直後に `<audio_backup_dir>/<日付>/<unit>/after-tts/` へ `assets/voice` と `audio_meta.json` を写す（`--no-backup` で止める）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import course_config  # noqa: E402
from lecture_movie import apply_readings as _apply_readings, load_readings  # noqa: E402

COURSE = course_config.load()

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

MODEL = COURSE.tts("model")
LANGUAGE_CODE = "ja-JP"
DEFAULT_VOICE = COURSE.tts("voice")
SAMPLE_RATE = 24000
CHUNK_MAX_CHARS = 250
CHUNK_GAP_SECONDS = 0.5
# 行の末尾に足す無音。**「図を見る時間を渡す」をここで決定的に作る。**
# 演技指示（prompt）は当たり外れがあるので間の管理には使わない（下の注記）。
LINE_TAIL_SECONDS = 0.35

# ★ TTS に渡す文字列だけを置き換える読みの補正（SCRIPT.md・字幕は台本の表記のまま）。
# 辞書は講座の `tts-readings.tsv`（`表記<TAB>読み`。lecture_movie.py と同じ形式）。書き方と注意は references/tts-readings.md。
#   - かなに直せば直るとは限らない（かなを続けると隣の語とくっついて別の語に読まれた）。読点で離すと直ることがある
#   - 英字の語は check_reading.py が比べない（漢字・かなだけを比べる）。音は hira_check.py で確かめる
#   - 足すときは「日付・ユニット・どう誤読したか・何回中何回直ったか」をコメントに書く
READINGS: list[tuple[str, str]] = []


def apply_readings(text: str) -> str:
    return _apply_readings(text, READINGS)


# `## Line N — ラベル (Frame N)` から担当フレーム番号を取る（make_srt.py と同じ規則）
LINE_RE = re.compile(r"^##\s+Line\s+\d+.*?\(Frame\s+(\d+)\)", re.I)
VOICE_RE = re.compile(r"^\s*Voice\s*[：:]\s*(\S+)")


def spoken_by_frame(script: Path) -> dict[int, str]:
    """フレーム番号 → 台詞。`## Line` 見出しの下の**字下げ行**だけを台詞とみなす。

    字下げしていない行は納品メモ（`**Delivery:**` など）なので読ませない。
    """
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


def load_voice_and_style(path: Path, default_voice: str = DEFAULT_VOICE) -> tuple[str, str]:
    """指示書から (話者, 演技指示) を取る。1行目の `Voice：X`、残りが prompt。"""
    raw = path.read_text(encoding="utf-8")
    voice = default_voice
    lines = raw.splitlines()
    body = lines
    if lines:
        m = VOICE_RE.match(lines[0])
        if m:
            voice = m.group(1)
            body = lines[1:]
    # 先頭の空行と区切り線は読み飛ばす（指示書によっては `Voice：` の直後が `---`）。
    # ここを飛ばさないと下の `---` 判定が即座に止まり、prompt が 0 文字になる。
    while body and (not body[0].strip() or body[0].strip() == "---"):
        body.pop(0)
    # 本文のあとの `---` 以降は運用メモなので prompt に混ぜない
    style: list[str] = []
    for line in body:
        if line.strip() == "---":
            break
        style.append(line)
    return voice, "\n".join(style).strip()


def chunk_text(text: str, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
    """句点（。！？）単位で max_chars 以下に割る。文が長すぎるときはそのまま通す。"""
    if len(text) <= max_chars:
        return [text]
    sentences = [s for s in re.split(r"(?<=[。！？])", text) if s.strip()]
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
    return chunks


# ★★ なぜ既定でスタイル指示（prompt）を使わないか（実測 2026-09-18）
#
# `gemini-3.1-flash-tts-preview` は、ごく普通の講座ナレーションでも
#   400 INVALID_ARGUMENT "... violates Vertex AI's usage guidelines"
# を返すことがある。**判定されているのは主に prompt 側**で、
# 台詞だけを prompt 無しで投げると 8行すべて通った。
#
# 実測でわかった性質:
#   - **(prompt, 台詞) の組ごとに判定は決定的。** 同じ組を3分以上かけて4周しても
#     `XOXXX` が完全に再現した。**同じ入力を投げ直しても通らない**し、
#     レート制限でもない（間を置いても変わらない）
#   - **しかし prompt を1文字変えると判定が入れ替わる。**
#     251字版では frame 4 だけが落ち、250字版では frame 4・6・8・9 が落ちた。
#     つまり分類器は不透明で、どの行が通るか事前に予測できない
#   - 長さ自体が原因ではない（中立な日本語 600字・英語 1200字は通る）。
#     特定の語も原因ではない（`NHKアナウンサー` `Accent:` は単独では通り
#     組み合わせで落ちる）
#   - prompt を短くすると率は改善するが、ゼロにはならない
#     （実測: prompt 無し 8/8 ・ 250字 3/8 ・ 251字 7/8 ・ 639字 6/8）
#
# ## 方針: 間の管理は prompt ではなく台本と無音で行う
#
# **通るまで prompt を変形し続けることはしない。** 中身が正当であっても
# それはフィルタ回避の形になる。
#
# そして**当たり外れのあるスタイル指示は、講座では素の声より悪い。**
# 1100行以上（140ユニット×約8行）のうち予測できない一部だけに演技指示が乗ると、
# 「間の取り方が行ごとに違う講座」になる。統一されているほうが価値が高い。
#
# ユーザーの要件「各文の後に一呼吸の間」「受講者が図を見る時間を渡す」は
# **prompt ではなくこちらで決定的に満たす。**
#   - 文中・文末の間 … 台本の読点と文の分割（`SCRIPT.md` が持つ）
#   - 行の後の間    … `LINE_TAIL_SECONDS` の無音（このファイルが持つ）
# どちらも再現可能で、レンダリングのたびに同じ結果になる。
#
# `--style` を付けると指示書の演技指示を使う。拒否された行は
# **スタイル指示なしの既定動作へ1回だけ縮退**し、どの行かを必ず表示する。


def strip_wav_header(blob: bytes) -> bytes:
    """API が返す LINEAR16 の応答から **RIFF ヘッダを剥がして** PCM だけにする。

    ★★ これが無いと「行と行の境目でパチッと鳴る」。

    `AudioEncoding.LINEAR16` の `audio_content` は**ヘッダ付きの WAV** で返る。
    それをそのまま連結すると、44バイトのヘッダが**音声サンプルとして**鳴る。
    実測（2026-09-18・56ファイル全部が該当）:

        先頭22サンプル = 18770 17990 <サイズ> 16727 17750 28006 8308 ...
        （`"RI" "FF" .. "WA" "VE" "fm" "t "` を int16 として読んだ値）
        ピーク振幅 **28,006〜30,336 = フルスケールの 85〜93%**・約 0.9ms

    行の末尾には `LINE_TAIL_SECONDS` の無音が付くので、聞こえ方は
    **「発話 → 0.35秒の無音 → パチッ → 次の発話」**になる。

    チャンク分割された行では**連結点の途中にも**ヘッダが入るので、
    ここで剥がすのが唯一の正しい場所。
    """
    if len(blob) < 12 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        return blob  # 既にヘッダ無し
    pos = 12
    while pos + 8 <= len(blob):
        chunk_id = blob[pos : pos + 4]
        chunk_size = int.from_bytes(blob[pos + 4 : pos + 8], "little")
        if chunk_id == b"data":
            # `data` の宣言サイズは実データより小さいことがある（末尾が切れる）ので、
            # 宣言を信用せず**残り全部**を返す。
            return blob[pos + 8 :]
        pos += 8 + chunk_size + (chunk_size & 1)
    raise ValueError("RIFF に data チャンクが無い")


def synthesize(
    client, text: str, style: str, voice: str, model: str, tail: float = LINE_TAIL_SECONDS
) -> tuple[bytes, bool]:
    """1行を (PCM, スタイル指示なしへ縮退したか) で返す。

    PCM はヘッダ無しの 24kHz / モノラル / 16bit。末尾に `tail` 秒の無音を足す。
    """
    from google.api_core import exceptions as gexc
    from google.cloud import texttospeech

    def call(chunk: str, prompt: str | None) -> bytes:
        resp = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=chunk, prompt=prompt),
            voice=texttospeech.VoiceSelectionParams(
                language_code=LANGUAGE_CODE, name=voice, model_name=model
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16
            ),
        )
        # ★ ヘッダを剥がす。これを忘れると連結点がクリックノイズになる
        return strip_wav_header(resp.audio_content)

    def silence(seconds: float) -> bytes:
        return b"\x00" * (int(SAMPLE_RATE * seconds) * 2)

    parts: list[bytes] = []
    degraded = False
    for chunk in chunk_text(apply_readings(text)):
        try:
            parts.append(call(chunk, style or None))
        except gexc.InvalidArgument as e:
            if "usage guidelines" not in str(e) or not style:
                raise
            # スタイル指示なしの既定動作へ縮退する（1回だけ・ここで打ち止め）
            parts.append(call(chunk, None))
            degraded = True
    return silence(CHUNK_GAP_SECONDS).join(parts) + silence(tail), degraded


def write_wav(path: Path, pcm: bytes) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return len(pcm) / 2 / SAMPLE_RATE


def backup(project: Path, made: list[str], meta_path: Path) -> Path:
    """作った直後の音声を退避する（Gemini-TTS は非決定的で、同じ音声は二度と作れない）。同じ日の2回目は -2 を付ける。"""
    import datetime
    import shutil

    base = COURSE.path("audio_backup_dir") / datetime.date.today().isoformat() / project.name / "after-tts"
    dest, i = base, 1
    while dest.exists():
        i += 1
        dest = base.with_name(f"after-tts-{i}")
    (dest / "assets" / "voice").mkdir(parents=True)
    for r in made:
        shutil.copy2(project / r, dest / r)
    shutil.copy2(meta_path, dest / meta_path.name)
    return dest


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="SCRIPT.md を Gemini-TTS で音声化する")
    ap.add_argument("project", help="Hyperframes プロジェクトのディレクトリ")
    ap.add_argument(
        "--instruction",
        default=None,
        help="ボイス指示書（既定: course.yaml の tts.instruction）",
    )
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--only", default=None, help="作り直すフレーム番号（例: 4,5）")
    ap.add_argument(
        "--style",
        action="store_true",
        help="指示書の演技指示を prompt として使う（既定は使わない。理由はソース冒頭の注記）",
    )
    ap.add_argument(
        "--tail",
        type=float,
        default=LINE_TAIL_SECONDS,
        help=f"各行の末尾に足す無音の秒数（既定 {LINE_TAIL_SECONDS}）。図を見る時間を作る",
    )
    ap.add_argument("--readings", default=None, help="読みの辞書（既定: course.yaml の tts.readings。無ければ置き換えない）")
    ap.add_argument("--no-backup", action="store_true", help="作った直後の退避をしない")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv[1:])

    project = COURSE.unit(a.project)
    script = project / "SCRIPT.md"
    if not script.is_file():
        print(f"FAIL: {script} がありません")
        return 1

    instruction = Path(a.instruction) if a.instruction else COURSE.tts_path("instruction")
    instruction = instruction.resolve()
    if not instruction.is_file():
        print(f"FAIL: ボイス指示書 {instruction} がありません")
        return 1

    global READINGS
    READINGS = load_readings(Path(a.readings) if a.readings else COURSE.tts_path("readings"))
    voice, style_notes = load_voice_and_style(instruction)
    # 話者は常に指示書から取る。演技指示は `--style` のときだけ使う
    style = style_notes if a.style else ""
    spoken = spoken_by_frame(script)
    if not spoken:
        print(f"FAIL: {script} から台詞を1行も抽出できませんでした")
        return 1

    only = None
    if a.only:
        only = {int(x) for x in re.findall(r"\d+", a.only)}

    print(f"話者: {voice} / モデル: {a.model} / 指示書: {instruction.name}")
    print(
        f"演技指示: {'使う（' + str(len(style)) + '字・縮退あり）' if style else '使わない（既定）'}"
        f" / 行末の無音: {a.tail}秒"
    )
    print(f"読みの辞書: {len(READINGS)} 語")
    print(f"台詞: {len(spoken)} 行" + (f"（うち {sorted(only)} のみ生成）" if only else ""))

    if a.dry_run:
        for frame in sorted(spoken):
            mark = " " if only is None or frame in only else "-"
            print(f" {mark} frame {frame:>2}: {len(spoken[frame]):>3}字  {spoken[frame]}")
            if apply_readings(spoken[frame]) != spoken[frame]:
                print(f"              TTS へ渡す文字列 → {apply_readings(spoken[frame])}")
        print("\n（--dry-run。API は呼んでいません）")
        return 0

    # クライアントの生成では API を呼ばないので、常に作っておく
    # （`--only` の指定が空でも、据え置き対象のファイルが欠けていれば合成に落ちる）
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()

    meta_path = project / "audio_meta.json"
    meta = {"bgm": None, "bgm_pending": False, "voices": [], "sfx": []}
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    prev = {int(v["frame"]): v for v in meta.get("voices", []) if v.get("frame") is not None}

    voices: list[dict] = []
    made: list[str] = []
    total = 0.0
    degraded: list[int] = []
    for frame in sorted(spoken):
        rel = f"assets/voice/{frame:02d}.wav"
        out = project / rel
        text = spoken[frame]
        if only is not None and frame not in only and out.is_file():
            entry = prev.get(frame)
            if entry:
                voices.append(entry)
                total += float(entry.get("duration_s") or 0)
                print(f"  frame {frame:>2}: 据え置き {entry.get('duration_s')}s")
                continue
        pcm, fell_back = synthesize(client, text, style, voice, a.model, a.tail)
        dur = round(write_wav(out, pcm), 3)
        total += dur
        voices.append({"frame": frame, "path": rel, "duration_s": dur, "words": []})
        made.append(rel)
        note = "  ← ★スタイル指示なしへ縮退" if fell_back else ""
        if fell_back:
            degraded.append(frame)
        print(f"  frame {frame:>2}: {dur:>6.3f}s  ({len(text)}字 / {len(text) / dur:.2f}字/秒){note}")

    meta["voices"] = voices
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\nOK: {meta_path} を更新（{len(voices)}行 / 音声合計 {total:.2f}秒）")
    if made and not a.no_backup:
        dest = backup(project, made, meta_path)
        print(f"退避: {dest}（{len(made)} 本と audio_meta.json）")
    if degraded:
        print(
            f"★ frame {degraded} は content filter の誤検知でスタイル指示が乗っていません。\n"
            "  声は同じですが演技指示（間の取り方・強調）が効いていません。\n"
            "  気になる行は SCRIPT.md 側で手当てしてください（読点で間を作る・文を分ける）。"
        )
    print("次: python word_times.py <project>（読みの兆候を警告）→ python pad_audio.py <project>（行頭 0.6 / 行末 1.2 秒）"
          " → python make_beats.py <project> → node <faceless_scripts>/audio.mjs sync-durations --audio-meta ./audio_meta.json --storyboard ./STORYBOARD.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
