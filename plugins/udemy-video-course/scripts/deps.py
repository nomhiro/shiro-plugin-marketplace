# -*- coding: utf-8 -*-
"""起動時の依存チェック。足りないものがあれば、処理を始める前に止める。

なぜ要るか（実測）: PATH の先頭の Python が別の環境に入れ替わり、必要なパッケージが無いまま
処理が**黙って**一部を飛ばした（成功の終了コードで終わり、気づいたのは完成動画を見たとき）。
どの Python で動いているかを毎回表示し、工程に要るものを先に確かめる。

    python deps.py                  # 全グループの有無を表示
    python deps.py tts video        # 指定したグループだけ確かめる（足りなければ終了コード 2）

スクリプトからは `preflight({"tts", "video"})` を呼ぶ。工程ごとに要るものだけを見るので、
`--audio-only` で soffice を要求したりはしない。
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys

# グループ → (Python モジュール, 実行ファイル, 用途)
GROUPS: dict[str, tuple[tuple[str, ...], tuple[str, ...], str]] = {
    "tts": (("google.cloud.texttospeech", "google.api_core"), ("ffmpeg",), "音声合成（Gemini-TTS）"),
    "pptx": (("pptx",), (), "スライド枚数の取得"),
    "video": (("fitz",), ("ffmpeg", "ffprobe", "soffice"), "スライドの PNG 化と動画の合成"),
    "practice": (("numpy",), ("ffmpeg", "ffprobe"), "録画の正規化と区間の合成"),
    "stt": (("azure.cognitiveservices.speech", "azure.identity"), ("ffmpeg",), "音声の照合（verify_tts）"),
    "qa": (("numpy",), ("ffmpeg", "ffprobe"), "完成動画の検査"),
    "ocr": (("rapidocr_onnxruntime", "cv2", "numpy", "PIL", "yaml"), (), "OCR による黒塗りと塗り残しの点検"),
    "image": (("PIL", "numpy"), (), "フレームの加工"),
}
# 段階2（scenes.yaml と cue の同期）を入れたら "sync": (("faster_whisper",), ...) をここに足し、
# cue があるのに無ければ止める（--no-timing を明示したときだけ飛ばす）。

_SOFFICE_CANDIDATES = (
    r"C:/Program Files/LibreOffice/program/soffice.com",
    r"C:/Program Files (x86)/LibreOffice/program/soffice.com",
    r"C:/Program Files/LibreOffice/program/soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):      # 親パッケージが無いと find_spec 自体が失敗する
        return False


def has_exe(name: str) -> bool:
    if shutil.which(name):
        return True
    if name == "soffice":
        return any(os.path.exists(p) for p in _SOFFICE_CANDIDATES)
    return False


def missing(groups: set[str]) -> list[str]:
    """足りないものを「グループ: 名前」の形で返す。"""
    out = []
    for g in sorted(groups):
        mods, exes, _ = GROUPS[g]
        out += [f"{g}: Python モジュール {m}" for m in mods if not has_module(m)]
        out += [f"{g}: 実行ファイル {e}" for e in exes if not has_exe(e)]
    return out


def preflight(groups: set[str], *, quiet: bool = False) -> None:
    """足りなければ終了コード 2 で止める。どの Python で動いているかを必ず出す。"""
    if not quiet:
        print(f"  python: {sys.executable}")
    lack = missing(groups)
    if lack:
        print("✗ 依存が足りません（処理を始める前に止めました）:", file=sys.stderr)
        for x in lack:
            print(f"   - {x}", file=sys.stderr)
        print("  `pip install -r scripts/requirements.txt` を、上に表示した Python で実行してください。",
              file=sys.stderr)
        sys.exit(2)


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    groups = set(argv) or set(GROUPS)
    unknown = groups - set(GROUPS)
    if unknown:
        print(f"未知のグループ: {', '.join(sorted(unknown))}（{', '.join(GROUPS)}）", file=sys.stderr)
        return 2
    print(f"python: {sys.executable}")
    bad = 0
    for g in sorted(groups):
        lack = missing({g})
        bad += bool(lack)
        print(f"  {'OK' if not lack else 'NG'} {g:9} {GROUPS[g][2]}" + ("" if not lack else "  ← " + "、".join(x.split(': ', 1)[1] for x in lack)))
    return 2 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
