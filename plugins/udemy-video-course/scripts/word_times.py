"""生成音声の**語単位の発話時刻**を取り出す。図解のビートを台詞に合わせるため。

## なぜ必要か

フレームの内部タイムラインは台詞の語に紐づいている。例（サンプルのフレーム4）:

    var CELLS = [
      { face: ".f04fc-face-tp", at: 2.02 }  /* 当てた陽性がTP */,
      { face: ".f04fc-face-fp", at: 3.44 }  /* 空振りがFP */,
      ...

台本を直したり TTS を差し替えると**この秒数が全部ずれる。**
比例伸縮で当てるのは近似にすぎない（読み上げの遅速は語によって違う）。
**実際に何秒でその語が発話されたかを測って入れる**のが正しい。

Google Speech-to-Text は `enable_word_time_offsets` で語ごとの開始・終了を返す。
生成した音声をそのまま認識にかけ、**探したい語の実測時刻**を出す。

## 使い方

    # 全行の語タイムスタンプを一覧
    python word_times.py videos/confusion-matrix-explained

    # 図解のビートに使う語だけを拾う（フレーム指定・語指定）
    python word_times.py videos/confusion-matrix-explained --frame 4 --find TP,FP,FN,TN
    python word_times.py videos/confusion-matrix-explained --frame 8 --find 適合率,再現率

認識は完全ではない（`混同行列`→`近藤行列` のような同音の取り違えが出る）。
**読みが正しいかの判定は `check_reading.py`、時刻取得はこちら。**
"""

from __future__ import annotations

import argparse
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


def words_for(client, speech, wav: bytes) -> list[tuple[str, float, float]]:
    cfg = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=SAMPLE_RATE,
        language_code="ja-JP",
        enable_word_time_offsets=True,
        # 2026-10-11（第5章 c5a の指摘）: 句読点なし＋WAV ヘッダ付きのまま渡すと、語が数秒ぶん落ちることがある
        # （check_reading は句読点ありで全文を取るので気づけない）。句読点を有効にし、ヘッダ(44B)は剥がして渡す。
        enable_automatic_punctuation=True,
        model="latest_long",
    )
    if wav[:4] == b"RIFF":
        wav = wav[44:]
    resp = client.recognize(config=cfg, audio=speech.RecognitionAudio(content=wav), timeout=180)  # 2026-10-12: 無限待ちを避ける（c5f/c63 が10分以上止まった）
    out: list[tuple[str, float, float]] = []
    for result in resp.results:
        for w in result.alternatives[0].words:
            out.append((w.word, w.start_time.total_seconds(), w.end_time.total_seconds()))
    return out


# 「決定木」の誤読の兆候（2026-09-22）。STT は もく=木 / じゅつ=技術 / 濁らない=機 と書き起こす。
# 正しい「けっていぎ」は `決定` + `技`（儀・義も可）。生成のたびにここで気づく。
SUSPECT_AFTER_KETTEI = {"木": "もく／ぼく と読まれた可能性", "技術": "ぎじゅつ と読まれた可能性", "機": "濁らず き と読まれた可能性"}


def suspicious(words) -> list[str]:
    out = []
    for i, (w, _s, _e) in enumerate(words[:-1]):
        if w == "決定" and words[i + 1][0] in SUSPECT_AFTER_KETTEI:
            out.append(f"決定木の読み: `決定`+`{words[i + 1][0]}` → {SUSPECT_AFTER_KETTEI[words[i + 1][0]]}（{words[i + 1][1]:.2f}s 付近）。耳で確認して、必要なら作り直す")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="生成音声の語単位の発話時刻を出す")
    ap.add_argument("project")
    ap.add_argument("--frame", type=int, default=None, help="1つのフレームだけ見る")
    ap.add_argument("--find", default=None, help="探す語（カンマ区切り）。例: TP,FP,FN,TN")
    a = ap.parse_args(argv[1:])

    project = Path(a.project)
    spoken = spoken_by_frame(project / "SCRIPT.md")
    frames = [a.frame] if a.frame else sorted(spoken)
    targets = [t.strip() for t in a.find.split(",")] if a.find else []

    from google.cloud import speech

    client = speech.SpeechClient()

    for f in frames:
        wav = project / f"assets/voice/{f:02d}.wav"
        if not wav.is_file():
            print(f"frame {f}: {wav} がありません")
            continue
        words = words_for(client, speech, wav.read_bytes())
        for warn in suspicious(words):
            print(f"\n  ⚠ frame {f}: {warn}")
        print(f"\n=== frame {f} ===")
        print(f"  台本: {spoken.get(f, '')}")
        if targets:
            for t in targets:
                hits = [
                    (w, s, e)
                    for w, s, e in words
                    # 認識結果は小文字化・記号落ちがあるので緩く照合する
                    if re.sub(r"\W", "", t).lower() in re.sub(r"\W", "", w).lower()
                ]
                if hits:
                    for w, s, e in hits:
                        print(f"  「{t}」→ {s:6.2f}s 〜 {e:5.2f}s   （認識語: {w}）")
                else:
                    print(f"  「{t}」→ 見つかりません")
        else:
            for w, s, e in words:
                print(f"  {s:6.2f}s 〜 {e:5.2f}s  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
