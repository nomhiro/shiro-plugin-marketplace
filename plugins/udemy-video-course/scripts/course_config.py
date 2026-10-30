# -*- coding: utf-8 -*-
"""講座ごとの値を `course.yaml` から読む（Hyperframes のスライド型の道具が共通で使う）。

道具に講座の値（章フォルダの表・受講者像・雛形の場所・Hyperframes の版など）を埋めると、
講座ごとに道具を写して直すことになり、直しが片方の講座にしか入らなくなる（実際に起きた）。
そこで値は講座のリポジトリの直下に置いた `course.yaml` に書き、道具はここから読む。

`course.yaml` は、作業ディレクトリから上へたどって最初に見つかったものを使う。
環境変数 COURSE_ROOT があれば、その下の `course.yaml` を使う。
見つからなければ、作業ディレクトリを講座の直下とみなし、下の DEFAULTS で動く。

雛形は `templates/course.example.yaml`。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "course.yaml"

DEFAULTS: dict = {
    "audience": "",                          # STORYBOARD・BRIEF の audience に入る受講者像（1行）
    "videos_dir": "videos",                  # ユニット（videos/<slug>/）を置く場所
    "lectures_dir": "lectures",              # ユニット doc（解説ドキュメント）を置く場所
    "template_dir": "videos/_template",      # 新しいユニットに写す枠組み（frame.md・hyperframes.json・フォント）
    "lectures_out_dir": "videos/_lectures",  # 冒頭・本体・末尾を連結した講義の出力先
    "audio_backup_dir": "videos/_audio-backup",
    "chapter_dirs": {},                      # {章番号: "01_xxx"}。doc-id の L<章>-… から lectures/ 下のフォルダを決める
    "doc_kind_tokens": {"lecture": "座学_", "handson": "実践_", "frame": ""},  # ユニット doc の名前に入れる種別
    "handson_suffix": "-handson",            # 実践の本体のユニット名の末尾
    "handson_line1": "",                     # 実践の本体の SCRIPT.md の Line 1 の雛形（空なら make_unit.py の既定）
    "parts_dir": "videos/_shared",           # 講座の部品（slides.py が import する *_parts.py）。unit_build.py が PYTHONPATH に入れる
    "doc_refs": [],                          # ユニット doc の「参照」に並べる講座の資料（例: research/learning-guide.md）
    "slide_format_doc": "",                  # 型の文書（ユニットの BRIEF に書く）。空ならプラグインの references/slide-format.md
    "hyperframes_version": "0.8.149",        # npx hyperframes@<版>。講座の途中で版を変えない（描画が変わる）
    "faceless_scripts": "~/.claude/skills/faceless-explainer/scripts",  # assemble-index.mjs・transitions.mjs・audio.mjs
    "tts": {
        "voice": "Callirrhoe",
        "model": "gemini-3.1-flash-tts-preview",
        "instruction": "tts-instruction.md",  # 1行目が `Voice：<名前>`。既定では声の名前だけを使う
        "readings": "tts-readings.tsv",       # 読みの辞書（`表記<TAB>読み`）。TTS に渡す文だけを置き換える
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def find_root(start: Path | None = None) -> tuple[Path, Path | None]:
    """(講座の直下, course.yaml のパス or None) を返す。"""
    env = os.environ.get("COURSE_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        cfg = root / CONFIG_NAME
        return root, (cfg if cfg.is_file() else None)
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / CONFIG_NAME).is_file():
            return d, d / CONFIG_NAME
    return here, None


@dataclass
class Course:
    root: Path
    config_path: Path | None
    data: dict = field(default_factory=dict)

    def path(self, key: str) -> Path:
        """`videos_dir` などの相対パスを講座の直下から解決する。"""
        return (self.root / self.data[key]).resolve()

    @property
    def videos(self) -> Path:
        return self.path("videos_dir")

    @property
    def lectures(self) -> Path:
        return self.path("lectures_dir")

    @property
    def template(self) -> Path:
        return self.path("template_dir")

    @property
    def audience(self) -> str:
        return str(self.data.get("audience") or "")

    @property
    def chapter_dirs(self) -> dict[int, str]:
        return {int(k): str(v) for k, v in (self.data.get("chapter_dirs") or {}).items()}

    @property
    def hyperframes(self) -> str:
        """npx に渡すパッケージ名（`hyperframes@0.8.149`）。"""
        return f"hyperframes@{self.data['hyperframes_version']}"

    @property
    def faceless_scripts(self) -> Path:
        return Path(os.path.expanduser(str(self.data["faceless_scripts"])))

    def tts(self, key: str):
        return self.data["tts"][key]

    def tts_path(self, key: str) -> Path:
        return (self.root / self.data["tts"][key]).resolve()

    def unit(self, slug_or_path: str | Path) -> Path:
        """ユニットの名前（`genai-risks`）でもパス（`videos/genai-risks`）でも、ユニットのディレクトリを返す。"""
        p = Path(slug_or_path)
        if p.is_dir():
            return p.resolve()
        cand = self.root / p
        if cand.is_dir():
            return cand.resolve()
        return (self.videos / p.name).resolve()


def load(start: Path | None = None) -> Course:
    root, cfg = find_root(start)
    data = DEFAULTS
    if cfg is not None:
        import yaml

        data = _merge(DEFAULTS, yaml.safe_load(cfg.read_text(encoding="utf-8")) or {})
    return Course(root=root, config_path=cfg, data=data)


if __name__ == "__main__":
    c = load()
    print(f"講座の直下: {c.root}")
    print(f"設定: {c.config_path or '（無し。既定値で動く）'}")
    for k in ("videos_dir", "lectures_dir", "template_dir", "hyperframes_version", "faceless_scripts"):
        print(f"  {k}: {c.data[k]}")
    print(f"  章フォルダ: {len(c.chapter_dirs)} 件 / 受講者像: {c.audience or '（空）'}")
