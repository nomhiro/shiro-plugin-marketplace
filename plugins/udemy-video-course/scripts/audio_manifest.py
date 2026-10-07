# -*- coding: utf-8 -*-
"""音声フォルダの manifest（どの wav を、どの本文・モデル・声で作ったか）を扱う。

lecture_movie.py（座学）と practice_movie.py（実践）が共通で使う。

なぜ要るか（実測）:
  - **台本を直しても wav が古いまま残る。** 座学は「wav があれば作らない」だったので、
    直した区間の wav を手で消し忘れると、古い音声のまま動画が組まれた（強調のきっかけにする
    語が音声に無く、10件が照合に落ちた）。本文のハッシュを持ち、変わった区間だけ作り直す。
  - **1本の中でモデルが混ざる。** モデルを切り替えたとき、本文が変わらない区間は古いモデルの
    wav のまま skip され、スライドごとに声の質が変わった。manifest にモデルと声を残し、
    既存の wav と違うモデルで作ろうとしたら**作る前に止める**。

形式（`<音声フォルダ>/.manifest.json`）:
    {"speech_01.wav": {"text": "<sha1>", "model": "<モデル名>", "voice": "<声>"}, ...}
古い版（実践）の `{"rec_01": "<sha1>"}` も読める（モデル・声は「不明」として扱う）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = ".manifest.json"


def text_digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def make_entry(text: str, model: str, voice: str) -> dict:
    return {"text": text_digest(text), "model": model, "voice": voice}


def load(audio_dir: Path) -> dict[str, dict]:
    """manifest を読む。無い・壊れているときは空。古い形式（値が文字列）は dict に直す。"""
    mf = audio_dir / MANIFEST_NAME
    if not mf.exists():
        return {}
    try:
        raw = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, dict] = {}
    for k, v in (raw or {}).items():
        if isinstance(v, str):
            out[k] = {"text": v, "model": None, "voice": None}
        elif isinstance(v, dict):
            out[k] = {"text": v.get("text"), "model": v.get("model"), "voice": v.get("voice")}
    return out


def save(audio_dir: Path, data: dict[str, dict]) -> None:
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / MANIFEST_NAME).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class Plan:
    """音声フェーズの計画。make＝合成する key、skip＝そのまま使う key、
    conflicts＝既存の wav が違うモデル・声（または不明）で作られている key と、その記録。"""
    make: list[str]
    skip: list[str]
    conflicts: list[tuple[str, str | None, str | None]]


def plan_audio(items: list[tuple[str, str]], existing: set[str], manifest: dict[str, dict],
               model: str, voice: str, force: bool = False) -> Plan:
    """items: [(key, 本文)]。existing: いま音声フォルダにある key の集合。

    - wav が無い／force／本文のハッシュが違う → 作る
    - 本文が同じ → そのまま使う。ただしモデルか声が今回と違う（記録が無い場合も含む）なら conflicts
    conflicts が空でなければ、呼び出し側は**何も合成せずに止める**（1本の中でモデルを混ぜない）。
    """
    make, skip, conflicts = [], [], []
    for key, text in items:
        rec = manifest.get(key)
        if force or key not in existing:
            make.append(key)
            continue
        if rec is not None and rec.get("text") not in (None, text_digest(text)):
            make.append(key)          # 台本が変わった
            continue
        skip.append(key)
        rmodel = rec.get("model") if rec else None
        rvoice = rec.get("voice") if rec else None
        if rmodel != model or rvoice != voice:
            conflicts.append((key, rmodel, rvoice))
    return Plan(make, skip, conflicts)


def conflict_message(conflicts: list[tuple[str, str | None, str | None]], model: str, voice: str,
                     audio_dir: Path) -> str:
    seen = sorted({f"{m or '不明（manifest に記録なし）'} / {v or '不明'}" for _, m, v in conflicts})
    keys = ", ".join(k for k, _, _ in conflicts[:6]) + (" …" if len(conflicts) > 6 else "")
    return (
        f"✗ 既存の音声が今回と違うモデル・声で作られています（今回: {model} / {voice}、既存: {'；'.join(seen)}）。\n"
        f"  対象: {keys}\n"
        "  1本の中でモデルを混ぜないため、何も合成せずに止めました。次のどれかで続けてください。\n"
        f"   - 全区間を作り直す：音声フォルダを別名へ退避（移動）してから再実行する（{audio_dir.name} → {audio_dir.name}.bak_<日付>）、または --force\n"
        "   - 既存の wav が今回と同じモデル・声で作られたと確かなら：--adopt-existing で manifest に記録だけする\n"
        "   - 既存の音声のモデルに合わせる：--model / --voice をそちらに合わせる")


def video_problems(items: list[tuple[str, str]], existing: set[str],
                   manifest: dict[str, dict]) -> tuple[list[str], list[str]]:
    """動画を組む前の点検。戻り値 (問題, 警告)。

    問題：本文がある区間の wav が無い／manifest の本文ハッシュが今の台本と違う（古い音声）／
          記録されたモデルが2種類以上（混在）。
    警告：manifest が無い（古い版で作った音声。本文の変化は確かめられない）。
    """
    problems, warnings = [], []
    missing = [k for k, _ in items if k not in existing]
    if missing:
        problems.append("音声が無い区間: " + ", ".join(missing))
    if not manifest:
        if existing:
            warnings.append("manifest が無いため、台本と音声が一致しているかを確かめられません"
                            "（古い版で作った音声）。一度 --audio-only を通すと記録されます。")
        return problems, warnings
    stale = [k for k, t in items if k in existing and k in manifest
             and manifest[k].get("text") not in (None, text_digest(t))]
    if stale:
        problems.append("台本が変わったのに音声が古い区間: " + ", ".join(stale)
                        + "（先に --audio-only を流す）")
    models = {(manifest[k].get("model"), manifest[k].get("voice"))
              for k, _ in items if k in manifest and manifest[k].get("model")}
    if len(models) > 1:
        problems.append("1本の中でモデル・声が混在: "
                        + "；".join(sorted(f"{m} / {v}" for m, v in models)))
    return problems, warnings
