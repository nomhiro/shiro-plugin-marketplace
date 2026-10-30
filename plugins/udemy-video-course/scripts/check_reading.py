"""生成音声を Speech-to-Text で書き起こし、台本と突き合わせて**読み誤りを洗う**。

## なぜ必要か

TTS が漢字を正しく読めているかを、**耳で聞いて確かめたことにしてはいけない。**
このプロジェクトの検証方針は「目視で済ませない」。読みも同じで機械で当てる。

旧構成（Kokoro）は漢字を読めず、`kana.py` でかな化して渡していた。
Gemini-TTS は漢字をそのまま読むが、**読めていることの確認は依然として必要**
（新しい専門用語・英略語・助数詞が出るたびに誤読の可能性がある）。

## 判定の読み方 — STT 側の正規化と誤認識を切り分ける

一致率が低くても TTS の誤読とは限らない。実測で出た例:

| 台本 | 認識 | 正体 |
|---|---|---|
| `99パーセント` | `99%` | STT の**正規化**。TTS は正しい |
| `混同行列` | `近藤 行列` | STT が「コンドウ」を人名と解釈。TTS は正しい |
| `TP` | `tp` | STT の小文字化。TTS は正しい |

**差分を必ず目で読んで、どちらの側の問題か判断すること。**
機械が出した数字だけで「合格」にも「不合格」にもしない。

## 付加・脱落の兆候（2026-10-08 追加・`udemy-video-course` 0.3.0 の `verify_tts.py` の判定を移植）

一致率（SequenceMatcher）は**読みの誤り**を拾う指標で、**台本に無い文を足す・全文を2回読む・
冒頭や末尾の1文が落ちる**事故は、長い行だと一致率が 0.9 を超えたまま通り抜ける。
そのため別の判定を並べて出す。比べるのは**漢字・ひらがな・カタカナだけ**（英字・数字は STT が別の表記で返すので比較に入れない。
カタカナ語の多い講座なので入れた。`SVM`↔`エスブイエム` のような表記ゆれは中ほどなら許容範囲）。

| 兆候 | 判定 |
|---|---|
| 付加 | 認識結果の2文字組のうち台本にある割合（適合率）が低い |
| 脱落 | 台本の2文字組のうち認識結果にある割合（再現率）が低い |
| 前置き・付け足し | 一致した範囲の前後に、認識結果の文字が `EXTRA_EDGE_CHARS` を超えて残る |
| 2回読み | 認識結果が台本の `DOUBLE_READ_RATIO` 倍を超える長さ |
| スタイル指示の読み上げ | `STYLE_LEAK_WORDS` が認識結果にだけ出る |

**兆候は失敗扱いにしない**（STT の取り違えでも出る）。出た行は書き起こしを読んで判断し、
本物なら**その行だけ** `tts.py --only` で作り直す（`CLAUDE.md`「音声は再現できない」）。

## 使い方

    python check_reading.py videos/confusion-matrix-explained
    python check_reading.py videos/... --threshold 0.95
    python check_reading.py videos/... --frame 4

読みを直したいときは **`SCRIPT.md` の表記を変える**のが第一手。
ただし聞き手にとって自然な直し方を選ぶ（文を分ける・語を言い換える）。
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tts import SAMPLE_RATE, spoken_by_frame  # noqa: E402

DEFAULT_THRESHOLD = 0.92

# 付加・脱落の兆候（上の docstring の表）。実測で調整したら理由を書き足すこと
BIGRAM_FLOOR = 0.6  # 適合率・再現率の下限。これを割ると兆候
EXTRA_EDGE_CHARS = 6  # 一致範囲の前後に残ってよい認識結果の文字数
DOUBLE_READ_RATIO = 1.6  # 認識結果 / 台本 の長さ。2回読みは 2.0 に近づく
MIN_BLOCK = 3  # 位置合わせに使う一致ブロックの最小長（偶然の一致を除く）
STYLE_LEAK_WORDS = ("オンライン講座", "語りかけ", "ナレーター", "カメラの前")

_KANA_KANJI = re.compile(r"[ぁ-ゖァ-ヺー一-鿿々]")


def normalize(s: str) -> str:
    """比較のノイズを落とす。句読点・空白・大小文字・単位表記の差は見ない。"""
    s = s.strip().lower()
    s = s.replace("パーセント", "%").replace("％", "%")
    return re.sub(r"[、。！？\s・]", "", s)


def _core(s: str) -> str:
    """漢字・かな・長音だけを残す（英字・数字は STT が別表記で返すので比べない）。"""
    return "".join(_KANA_KANJI.findall(s))


def _bigrams(s: str) -> set[str]:
    return {s[i : i + 2] for i in range(len(s) - 1)}


def suspicious(ref: str, hyp: str) -> list[str]:
    """台本 ref と書き起こし hyp から、付加・脱落・2回読みの兆候を文字列で返す。"""
    r, h = _core(ref), _core(hyp)
    flags: list[str] = []
    if len(r) < 4:
        return flags  # 短すぎて2文字組が当てにならない
    if not h:
        return ["認識結果が空（音声が無音・認識失敗の疑い。台本の問題ではない）"]

    rb, hb = _bigrams(r), _bigrams(h)
    recall = len(rb & hb) / len(rb)
    precision = len(rb & hb) / len(hb) if hb else 0.0
    if precision < BIGRAM_FLOOR:
        flags.append(f"付加の疑い: 適合率 {precision * 100:.0f}%（認識結果に台本に無い文字が多い）")
    if recall < BIGRAM_FLOOR:
        flags.append(f"脱落の疑い: 再現率 {recall * 100:.0f}%（台本の文字が読まれていない）")

    if len(h) > DOUBLE_READ_RATIO * len(r):
        flags.append(f"2回読みの疑い: 認識結果が台本の {len(h) / len(r):.1f} 倍の長さ")

    blocks = [b for b in difflib.SequenceMatcher(None, r, h, autojunk=False).get_matching_blocks() if b.size >= MIN_BLOCK]
    if blocks:
        first, last = blocks[0], blocks[-1]
        head = first.b - first.a
        tail = (len(h) - (last.b + last.size)) - (len(r) - (last.a + last.size))
        if head > EXTRA_EDGE_CHARS:
            flags.append(f"冒頭に前置きの疑い: 台本の冒頭より {head} 字多い「{h[: first.b]}」")
        if tail > EXTRA_EDGE_CHARS:
            flags.append(f"末尾に付け足しの疑い: 台本の末尾より {tail} 字多い「{h[last.b + last.size :]}」")
        # 冒頭・末尾の1文だけが落ちた場合（適合率も再現率も通り抜ける）
        if first.a - first.b > EXTRA_EDGE_CHARS:
            flags.append(f"冒頭の脱落の疑い: 台本の冒頭 {first.a - first.b} 字が読まれていない「{r[: first.a - first.b]}」")
        if (len(r) - (last.a + last.size)) - (len(h) - (last.b + last.size)) > EXTRA_EDGE_CHARS:
            flags.append("末尾の脱落の疑い: 台本の末尾が読まれていない")

    for w in STYLE_LEAK_WORDS:
        if w in hyp and w not in ref:
            flags.append(f"スタイル指示の読み上げの疑い:「{w}」が認識結果にだけある")
    return flags


def transcribe(client, speech, wav: bytes) -> str:
    cfg = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=SAMPLE_RATE,
        language_code="ja-JP",
        enable_automatic_punctuation=True,
        model="latest_long",
    )
    resp = client.recognize(config=cfg, audio=speech.RecognitionAudio(content=wav), timeout=180)  # 2026-10-12: 無限待ちを避ける（c5f/c63 が10分以上止まった）
    return "".join(r.alternatives[0].transcript for r in resp.results)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="生成音声の読みを台本と突き合わせる")
    ap.add_argument("project", help="Hyperframes プロジェクトのディレクトリ")
    ap.add_argument("--frame", type=int, default=None, help="1つのフレームだけ見る")
    ap.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"この一致率を下回った行を要確認として出す（既定 {DEFAULT_THRESHOLD}）",
    )
    a = ap.parse_args(argv[1:])

    project = Path(a.project)
    script = project / "SCRIPT.md"
    if not script.is_file():
        print(f"FAIL: {script} がありません")
        return 1
    spoken = spoken_by_frame(script)
    frames = [a.frame] if a.frame else sorted(spoken)

    from google.cloud import speech

    client = speech.SpeechClient()

    low: list[tuple[int, float, str, str]] = []
    sus: list[tuple[int, list[str]]] = []
    print(f"{'frame':<7}{'一致率':<9}書き起こし")
    for f in frames:
        wav = project / f"assets/voice/{f:02d}.wav"
        if not wav.is_file():
            print(f"  {f:<5}   ----   {wav} がありません")
            continue
        hyp = transcribe(client, speech, wav.read_bytes())
        ref = spoken.get(f, "")
        ratio = difflib.SequenceMatcher(None, normalize(ref), normalize(hyp)).ratio()
        print(f"  {f:<5} {ratio * 100:>6.1f}%  {hyp}")
        if ratio < a.threshold:
            low.append((f, ratio, ref, hyp))
        flags = suspicious(ref, hyp)
        if flags:
            sus.append((f, flags))

    if sus:
        print("\n=== 付加・脱落の兆候（一致率とは別の判定。書き起こしを読んで判断すること）===")
        for f, flags in sus:
            print(f"\nframe {f}")
            for fl in flags:
                print(f"  ! {fl}")
        print(
            "\n※ 本物なら、その行の wav だけを退避して `tts.py --only` で作り直す"
            "（全体を再生成しない。音声は再現できない）。"
        )
    else:
        print(f"\n付加・脱落の兆候: なし（全 {len(frames)} 行）")

    if not low:
        print(f"OK: 全 {len(frames)} 行が一致率 {a.threshold * 100:.0f}% 以上。")
        return 0

    print(f"\n=== 一致率が {a.threshold * 100:.0f}% 未満の行（差分を読んで判断すること）===")
    for f, ratio, ref, hyp in low:
        nr, nh = normalize(ref), normalize(hyp)
        print(f"\nframe {f}  {ratio * 100:.1f}%")
        print(f"  台本: {ref}")
        print(f"  認識: {hyp}")
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, nr, nh).get_opcodes():
            if tag != "equal":
                print(f"    {tag:<8} 台本「{nr[i1:i2]}」 → 認識「{nh[j1:j2]}」")
    print(
        "\n※ STT の正規化・同音の取り違えは TTS の誤読ではない"
        "（`99パーセント`→`99%`、`混同行列`→`近藤 行列` など）。"
    )
    # 要確認はあるが最終判断は人に委ねる。ここでは失敗扱いにしない
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
