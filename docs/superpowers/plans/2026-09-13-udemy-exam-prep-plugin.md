# udemy-exam-prep プラグイン 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI-103 で確立した Udemy 試験対策問題集ハーネスを、任意ベンダー・任意資格に対応する Claude Code プラグイン `udemy-exam-prep` として `nomhiro/shiro-plugin-marketplace` に切り出し、講座テンプレートの初期化スキルを含めて公開する。

**Architecture:** マーケットプレイスリポジトリ直下に `.claude-plugin/marketplace.json`、`plugins/udemy-exam-prep/` にプラグイン本体を置く。決定的な処理（front matter 検証・テンプレート展開・CSV 検証・選択肢シャッフル・配分検証）は `scripts/` の純 stdlib Python に実装し pytest で検証する。スキルとエージェントはこれらのスクリプトを呼び出すオーケストレーション層に徹する。資格固有の情報はプロジェクト側 `sections.md` の YAML front matter だけが持つ。

**Tech Stack:** Python 3.13（標準ライブラリのみ／PyYAML は front matter 解析に使用）、pytest、Claude Code プラグイン規約（`.claude-plugin/`、`skills/`、`agents/`、`.mcp.json`）、Playwright MCP

**Spec:** `docs/superpowers/specs/2026-09-13-udemy-exam-prep-plugin-design.md`

## Global Constraints

- リポジトリ: `C:\Users\nom40\Documents\shiro-plugin-marketplace`（git 初期化済み、`main` ブランチ、コミット `04833a5` に設計書あり）
- 公開先: `nomhiro/shiro-plugin-marketplace`（**Public**）、ライセンス **MIT**
- プラグイン名: `udemy-exam-prep`、バージョン `0.1.0`
- Python は **標準ライブラリ + PyYAML のみ**。他の外部依存を追加しない（環境: Python 3.13.5 / PyYAML 済 / pytest 済）
- CSV は **Udemy Practice Test Bulk Upload Template v2 の17カラム固定**。書き出しは `encoding='utf-8'`（BOM 禁止）、読み込みは `encoding='utf-8-sig'`、`newline=''` 必須
- 17カラムのヘッダーは以下で固定（1文字も変えない）:
  `Question,Question Type,Answer Option 1,Explanation 1,Answer Option 2,Explanation 2,Answer Option 3,Explanation 3,Answer Option 4,Explanation 4,Answer Option 5,Explanation 5,Answer Option 6,Explanation 6,Correct Answers,Overall Explanation,Domain`
- `Question Type` は `multiple-choice` / `multi-select` のみ
- セクション構成モードは `mock-exam` のみサポート（`mode` が他値なら明示エラーで停止）
- プラグイン root の `.mcp.json` は **`mcpServers` ラッパーを持たないフラットマップ**（公式 playwright プラグインと同形式）
- 移植元: `C:\Users\nom40\Documents\Udemy\AI-103\.claude\`（skills 7個・agents 3個）。**AI-103 側は変更しない**（併存方針）
- シャッフルの乱数シードは `42` 固定（決定的）
- スキル起動名はプラグイン名前空間付き `/udemy-exam-prep:<skill>` になる。テンプレート内の起動例はこの表記で書く
- 対応ベンダー enum: `anthropic` / `microsoft` / `github` / `cloudflare` / `ipa` / `generic`

---

### Task 1: リポジトリ土台とプラグインメタデータ

**Files:**
- Create: `.claude-plugin/marketplace.json`
- Create: `plugins/udemy-exam-prep/.claude-plugin/plugin.json`
- Create: `plugins/udemy-exam-prep/.mcp.json`
- Create: `README.md`
- Create: `LICENSE`
- Create: `.gitignore`
- Create: `pyproject.toml`
- Test: `tests/test_metadata.py`

**Interfaces:**
- Consumes: なし（最初のタスク）
- Produces: `plugins/udemy-exam-prep/` のディレクトリ位置と `PLUGIN_DIR` の慣習。以降の全タスクがこのパス配下にファイルを置く。pytest は**リポジトリルートから** `python -m pytest` で実行する（`pyproject.toml` の `testpaths = ["tests"]`）。

- [ ] **Step 1: Write the failing test**

`tests/test_metadata.py`:

```python
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "udemy-exam-prep"


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_marketplace_json_shape():
    m = _load(REPO / ".claude-plugin" / "marketplace.json")
    assert m["name"] == "shiro-plugin-marketplace"
    assert m["owner"]["name"] == "nomhiro"
    names = [p["name"] for p in m["plugins"]]
    assert names == ["udemy-exam-prep"]
    entry = m["plugins"][0]
    assert entry["source"] == "./plugins/udemy-exam-prep"
    assert entry["version"] == "0.1.0"
    assert entry["description"].strip()


def test_plugin_json_shape():
    p = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert p["name"] == "udemy-exam-prep"
    assert p["version"] == "0.1.0"
    assert p["description"].strip()
    assert p["author"]["name"] == "nomhiro"


def test_plugin_mcp_json_is_flat_map():
    m = _load(PLUGIN / ".mcp.json")
    # プラグイン root の .mcp.json は mcpServers ラッパーを持たない
    assert "mcpServers" not in m
    assert m["playwright"]["command"] == "npx"
    assert m["playwright"]["args"] == ["@playwright/mcp@latest"]


def test_license_is_mit():
    text = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/nom40/Documents/shiro-plugin-marketplace && python -m pytest tests/test_metadata.py -v`
Expected: FAIL — `FileNotFoundError` / collection error（`.claude-plugin/marketplace.json` が存在しない）

- [ ] **Step 3: Write minimal implementation**

`.claude-plugin/marketplace.json`:

```json
{
  "$schema": "https://code.claude.com/schemas/marketplace.json",
  "name": "shiro-plugin-marketplace",
  "owner": {
    "name": "nomhiro",
    "url": "https://github.com/nomhiro"
  },
  "metadata": {
    "description": "nomhiro's Claude Code plugins",
    "version": "0.1.0"
  },
  "plugins": [
    {
      "name": "udemy-exam-prep",
      "source": "./plugins/udemy-exam-prep",
      "description": "認定資格の試験対策問題集（Udemy 演習テスト講座）を、公式ドキュメント調査からフル模試生成・Udemy へのアップロードまで一貫して作成するハーネス",
      "version": "0.1.0",
      "author": { "name": "nomhiro" },
      "homepage": "https://github.com/nomhiro/shiro-plugin-marketplace",
      "repository": "https://github.com/nomhiro/shiro-plugin-marketplace",
      "license": "MIT",
      "keywords": ["udemy", "certification", "practice-test", "quiz", "exam-prep"]
    }
  ]
}
```

`plugins/udemy-exam-prep/.claude-plugin/plugin.json`:

```json
{
  "name": "udemy-exam-prep",
  "description": "認定資格の試験対策問題集（Udemy 演習テスト講座）を作成するハーネス。試験ブループリントの起草、公式ドキュメント調査、本番相当フル模試の生成・検証、Udemy へのアップロードまでをスキルとサブエージェントで自動化する",
  "version": "0.1.0",
  "author": { "name": "nomhiro" },
  "homepage": "https://github.com/nomhiro/shiro-plugin-marketplace",
  "license": "MIT"
}
```

`plugins/udemy-exam-prep/.mcp.json`:

```json
{
  "playwright": {
    "command": "npx",
    "args": ["@playwright/mcp@latest"]
  }
}
```

`pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["plugins/udemy-exam-prep"]
addopts = "-q"
```

`.gitignore`:

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.superpowers/
.claude/settings.local.json
Thumbs.db
.DS_Store
```

`LICENSE`: MIT License 全文（著作権表示は `Copyright (c) 2026 nomhiro`）

`README.md`: マーケットプレイスの追加手順とプラグイン一覧。最低限以下を含む。

```markdown
# shiro-plugin-marketplace

nomhiro の Claude Code プラグイン置き場。

## 追加

/plugin marketplace add nomhiro/shiro-plugin-marketplace
/plugin install udemy-exam-prep@shiro-plugin-marketplace

## プラグイン

| プラグイン | 説明 |
|---|---|
| udemy-exam-prep | 認定資格の試験対策問題集（Udemy 演習テスト講座）を作成するハーネス |
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metadata.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin plugins/udemy-exam-prep/.claude-plugin plugins/udemy-exam-prep/.mcp.json README.md LICENSE .gitignore pyproject.toml tests/test_metadata.py
git commit -m "feat: マーケットプレイスとプラグインのメタデータを追加"
```

---

### Task 2: 試験プロファイル（front matter）の読み取りと検証

**Files:**
- Create: `plugins/udemy-exam-prep/scripts/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: Task 1 の `pythonpath = ["plugins/udemy-exam-prep"]`（`from scripts.profile import ...` で読める）
- Produces:
  - `load_profile(sections_md: Path | str) -> dict` — `sections.md` 冒頭の YAML front matter を dict で返す。front matter が無い/壊れている場合は `ProfileError` を送出
  - `validate_profile(profile: dict) -> list[str]` — 違反メッセージのリスト。空リストなら妥当
  - `domain_quota(profile: dict) -> dict[str, int]` — `{"D1": 16, "D2": 11, ...}`
  - `domain_names(profile: dict) -> dict[str, str]` — `{"D1": "Agentic Architecture & Orchestration", ...}`（`Domain` 列に書く正式名の引き当てに使う）
  - `class ProfileError(Exception)`
  - CLI: `python plugins/udemy-exam-prep/scripts/profile.py <sections.md>` → 妥当なら `OK: ...` を出力して exit 0、違反があれば `FAIL:` と一覧を出力して exit 1
- 必須キー: `cert` / `cert_name` / `vendor` / `study_guide` / `mode` / `exam.minutes` / `exam.pass_score` / `exam.language` / `mock_exams` / `questions_per_exam` / `question_types` / `primary_sources` / `domains`
- `domains` の各要素の必須キー: `id` / `name` / `ratio` / `per_exam`

- [ ] **Step 1: Write the failing test**

`tests/test_profile.py`:

```python
import textwrap
import pytest
from scripts.profile import (
    ProfileError, load_profile, validate_profile, domain_quota, domain_names,
)

VALID = textwrap.dedent("""\
    ---
    cert: CCA-F
    cert_name: Claude Certified Architect - Foundations
    vendor: anthropic
    study_guide: https://example.com/guide
    mode: mock-exam
    exam:
      minutes: 120
      pass_score: 720
      max_score: 1000
      language: en
    mock_exams: 6
    questions_per_exam: 60
    question_types:
      multiple-choice: "70%"
      multi-select: "30%"
    primary_sources:
      - priority: 1
        tool: local-pdf
        scope: Exam Guide
    domains:
      - id: D1
        name: Agentic Architecture & Orchestration
        ratio: "27%"
        per_exam: 16
      - id: D2
        name: Tool Design & MCP Integration
        ratio: "18%"
        per_exam: 11
      - id: D3
        name: Claude Code Configuration & Workflows
        ratio: "20%"
        per_exam: 12
      - id: D4
        name: Prompt Engineering & Structured Output
        ratio: "20%"
        per_exam: 12
      - id: D5
        name: Context Management & Reliability
        ratio: "15%"
        per_exam: 9
    ---

    # 本文はここから
    """)


def write(tmp_path, text):
    p = tmp_path / "sections.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_profile_reads_front_matter(tmp_path):
    prof = load_profile(write(tmp_path, VALID))
    assert prof["cert"] == "CCA-F"
    assert prof["exam"]["minutes"] == 120
    assert len(prof["domains"]) == 5


def test_valid_profile_has_no_errors(tmp_path):
    assert validate_profile(load_profile(write(tmp_path, VALID))) == []


def test_missing_front_matter_raises(tmp_path):
    with pytest.raises(ProfileError):
        load_profile(write(tmp_path, "# front matter なし\n"))


def test_unterminated_front_matter_raises(tmp_path):
    with pytest.raises(ProfileError):
        load_profile(write(tmp_path, "---\ncert: X\n"))


def test_missing_required_key_is_reported(tmp_path):
    text = VALID.replace("cert_name: Claude Certified Architect - Foundations\n", "")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("cert_name" in e for e in errs)


def test_per_exam_sum_mismatch_is_reported(tmp_path):
    text = VALID.replace("per_exam: 9", "per_exam: 8")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("59" in e and "60" in e for e in errs)


def test_duplicate_domain_id_is_reported(tmp_path):
    text = VALID.replace("id: D5", "id: D4")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("duplicate" in e.lower() for e in errs)


def test_non_mock_exam_mode_is_reported(tmp_path):
    text = VALID.replace("mode: mock-exam", "mode: topic-section")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("mode" in e for e in errs)


def test_unknown_vendor_is_reported(tmp_path):
    text = VALID.replace("vendor: anthropic", "vendor: acme")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("vendor" in e for e in errs)


def test_zero_mock_exams_is_reported(tmp_path):
    text = VALID.replace("mock_exams: 6", "mock_exams: 0")
    errs = validate_profile(load_profile(write(tmp_path, text)))
    assert any("mock_exams" in e for e in errs)


def test_domain_quota_and_names(tmp_path):
    prof = load_profile(write(tmp_path, VALID))
    assert domain_quota(prof) == {"D1": 16, "D2": 11, "D3": 12, "D4": 12, "D5": 9}
    assert domain_names(prof)["D3"] == "Claude Code Configuration & Workflows"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts'`

- [ ] **Step 3: Write minimal implementation**

`plugins/udemy-exam-prep/scripts/__init__.py`: 空ファイル

`plugins/udemy-exam-prep/scripts/profile.py`:

```python
"""sections.md の YAML front matter（試験プロファイル）を読み取り検証する。

harness の唯一の入力インターフェース。資格固有の情報はすべてここから来る。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

VENDORS = ("anthropic", "microsoft", "github", "cloudflare", "ipa", "generic")
MODES = ("mock-exam",)

REQUIRED_TOP = (
    "cert", "cert_name", "vendor", "study_guide", "mode",
    "exam", "mock_exams", "questions_per_exam",
    "question_types", "primary_sources", "domains",
)
REQUIRED_EXAM = ("minutes", "pass_score", "language")
REQUIRED_DOMAIN = ("id", "name", "ratio", "per_exam")


class ProfileError(Exception):
    """front matter が読めない・壊れている。"""


def load_profile(sections_md) -> dict:
    path = Path(sections_md)
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ProfileError(f"{path}: front matter の開始 '---' が先頭行にない")
    try:
        end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
    except StopIteration:
        raise ProfileError(f"{path}: front matter の終端 '---' が見つからない") from None
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as e:
        raise ProfileError(f"{path}: front matter の YAML 解析に失敗: {e}") from e
    if not isinstance(data, dict):
        raise ProfileError(f"{path}: front matter がマッピングではない")
    return data


def validate_profile(profile: dict) -> list[str]:
    errs: list[str] = []

    for key in REQUIRED_TOP:
        if key not in profile:
            errs.append(f"必須キー '{key}' がない")

    vendor = profile.get("vendor")
    if vendor is not None and vendor not in VENDORS:
        errs.append(f"vendor '{vendor}' は未対応。{VENDORS} のいずれかにする")

    mode = profile.get("mode")
    if mode is not None and mode not in MODES:
        errs.append(f"mode '{mode}' は未対応。現状 {MODES} のみサポート")

    exam = profile.get("exam")
    if isinstance(exam, dict):
        for key in REQUIRED_EXAM:
            if key not in exam:
                errs.append(f"必須キー 'exam.{key}' がない")
    elif "exam" in profile:
        errs.append("exam がマッピングではない")

    for key in ("mock_exams", "questions_per_exam"):
        val = profile.get(key)
        if val is not None and (not isinstance(val, int) or val < 1):
            errs.append(f"{key} は 1 以上の整数にする（現在: {val!r}）")

    domains = profile.get("domains")
    if not isinstance(domains, list) or not domains:
        if "domains" in profile:
            errs.append("domains が非空のリストではない")
        return errs

    seen: set[str] = set()
    total = 0
    for i, d in enumerate(domains, 1):
        if not isinstance(d, dict):
            errs.append(f"domains[{i}] がマッピングではない")
            continue
        for key in REQUIRED_DOMAIN:
            if key not in d:
                errs.append(f"domains[{i}] に必須キー '{key}' がない")
        did = d.get("id")
        if did in seen:
            errs.append(f"domains[{i}]: duplicate domain id '{did}'")
        if did is not None:
            seen.add(did)
        per = d.get("per_exam")
        if isinstance(per, int):
            total += per
        elif per is not None:
            errs.append(f"domains[{i}]: per_exam が整数ではない（{per!r}）")

    qpe = profile.get("questions_per_exam")
    if isinstance(qpe, int) and total != qpe:
        errs.append(f"per_exam の合計 {total} が questions_per_exam {qpe} と一致しない")

    return errs


def domain_quota(profile: dict) -> dict[str, int]:
    return {d["id"]: d["per_exam"] for d in profile["domains"]}


def domain_names(profile: dict) -> dict[str, str]:
    return {d["id"]: d["name"] for d in profile["domains"]}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: profile.py <sections.md>", file=sys.stderr)
        return 2
    try:
        profile = load_profile(argv[1])
    except ProfileError as e:
        print(f"FAIL: {e}")
        return 1
    errs = validate_profile(profile)
    if errs:
        print(f"FAIL: {len(errs)} error(s)")
        for e in errs:
            print(f"  - {e}")
        return 1
    q = domain_quota(profile)
    print(
        f"OK: {profile['cert']} / mode={profile['mode']} / "
        f"{profile['mock_exams']} exams x {profile['questions_per_exam']} questions / "
        f"quota={q}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_profile.py -v`
Expected: PASS（11 passed）

- [ ] **Step 5: Commit**

```bash
git add plugins/udemy-exam-prep/scripts/__init__.py plugins/udemy-exam-prep/scripts/profile.py tests/test_profile.py
git commit -m "feat: 試験プロファイル（sections.md front matter）の読み取りと検証"
```

---

### Task 3: 講座テンプレートと初期化スクリプト

**Files:**
- Create: `plugins/udemy-exam-prep/templates/exam-course/CLAUDE.md.tmpl`
- Create: `plugins/udemy-exam-prep/templates/exam-course/sections.md.tmpl`
- Create: `plugins/udemy-exam-prep/templates/exam-course/question-bank.md.tmpl`
- Create: `plugins/udemy-exam-prep/templates/exam-course/removed-questions.md.tmpl`
- Create: `plugins/udemy-exam-prep/templates/exam-course/gitignore.tmpl`
- Create: `plugins/udemy-exam-prep/templates/exam-course/PracticeTestBulkQuestionUploadTemplate_v2.csv`
- Create: `plugins/udemy-exam-prep/scripts/init_course.py`
- Test: `tests/test_init_course.py`

**Interfaces:**
- Consumes: Task 2 の `scripts.profile.load_profile` / `validate_profile`（展開後の `sections.md` を自己検証するため）
- Produces:
  - `PLACEHOLDERS: tuple[str, ...]` — `("CERT_ID", "CERT_NAME", "VENDOR", "STUDY_GUIDE_URL", "EXAM_MINUTES", "PASS_SCORE", "MOCK_EXAMS", "QUESTIONS_PER_EXAM")`
  - `render(text: str, values: dict[str, str]) -> str` — `{{KEY}}` を置換。未知の `{{...}}` が残ったら `InitError`
  - `init_course(dest: Path, values: dict[str, str], template_dir: Path | None = None) -> dict[str, list[str]]` — `{"created": [...], "skipped": [...]}` を返す。既存ファイルは上書きせず `skipped` に入れる。`gitignore.tmpl` は `.gitignore` として書く。`.csv` は置換せずバイト単位でコピー
  - `class InitError(Exception)`
  - CLI: `python plugins/udemy-exam-prep/scripts/init_course.py --dest <dir> --cert CCA-F --cert-name "..." --vendor anthropic --study-guide "..." --exam-minutes 120 --pass-score 720 --mock-exams 6 --questions-per-exam 60`
- テンプレート名 → 出力名の対応: `*.tmpl` は末尾 `.tmpl` を除去、`gitignore` は `.gitignore` にリネーム、それ以外はそのまま

- [ ] **Step 1: Write the failing test**

`tests/test_init_course.py`:

```python
import pytest
from pathlib import Path
from scripts.init_course import InitError, PLACEHOLDERS, init_course, render
from scripts.profile import load_profile, validate_profile

VALUES = {
    "CERT_ID": "CCA-F",
    "CERT_NAME": "Claude Certified Architect - Foundations",
    "VENDOR": "anthropic",
    "STUDY_GUIDE_URL": "https://example.com/guide",
    "EXAM_MINUTES": "120",
    "PASS_SCORE": "720",
    "MOCK_EXAMS": "6",
    "QUESTIONS_PER_EXAM": "60",
}

EXPECTED_FILES = {
    "CLAUDE.md",
    "sections.md",
    "question-bank.md",
    "removed-questions.md",
    ".gitignore",
    "PracticeTestBulkQuestionUploadTemplate_v2.csv",
}


def test_placeholders_are_exactly_eight():
    assert len(PLACEHOLDERS) == 8
    assert set(PLACEHOLDERS) == set(VALUES)


def test_render_substitutes_known_keys():
    assert render("cert: {{CERT_ID}}", VALUES) == "cert: CCA-F"


def test_render_rejects_unreplaced_placeholder():
    with pytest.raises(InitError):
        render("x: {{NOT_A_KEY}}", VALUES)


def test_init_course_creates_all_files(tmp_path):
    result = init_course(tmp_path, VALUES)
    assert set(result["created"]) == EXPECTED_FILES
    assert result["skipped"] == []
    for name in EXPECTED_FILES:
        assert (tmp_path / name).is_file()


def test_no_placeholder_survives_expansion(tmp_path):
    init_course(tmp_path, VALUES)
    for name in EXPECTED_FILES:
        if name.endswith(".csv"):
            continue
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert "{{" not in text, f"{name} に未置換のプレースホルダが残っている"


def test_expanded_sections_md_has_a_valid_profile(tmp_path):
    init_course(tmp_path, VALUES)
    profile = load_profile(tmp_path / "sections.md")
    assert profile["cert"] == "CCA-F"
    assert profile["vendor"] == "anthropic"
    assert profile["exam"]["minutes"] == 120
    assert profile["mock_exams"] == 6
    assert profile["questions_per_exam"] == 60
    # ドメイン表はテンプレート段階では未確定なので domains 欠落エラーだけが出る
    errs = validate_profile(profile)
    assert all("domains" in e for e in errs), errs


def test_init_course_is_idempotent_and_never_overwrites(tmp_path):
    init_course(tmp_path, VALUES)
    (tmp_path / "CLAUDE.md").write_text("手で編集した内容", encoding="utf-8")
    result = init_course(tmp_path, VALUES)
    assert result["created"] == []
    assert set(result["skipped"]) == EXPECTED_FILES
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "手で編集した内容"


def test_csv_template_has_the_17_column_header(tmp_path):
    init_course(tmp_path, VALUES)
    header = (tmp_path / "PracticeTestBulkQuestionUploadTemplate_v2.csv").read_text(
        encoding="utf-8-sig"
    ).splitlines()[0]
    assert len(header.split(",")) == 17
    assert header.startswith("Question,Question Type,Answer Option 1,Explanation 1,")
    assert header.endswith("Correct Answers,Overall Explanation,Domain")


def test_written_files_have_no_bom(tmp_path):
    init_course(tmp_path, VALUES)
    for name in EXPECTED_FILES:
        raw = (tmp_path / name).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{name} に BOM がある"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_init_course.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.init_course'`

- [ ] **Step 3: Write minimal implementation**

`plugins/udemy-exam-prep/scripts/init_course.py`:

```python
"""講座テンプレートを展開して新しい試験対策プロジェクトを初期化する。

既存ファイルは絶対に上書きしない（skip して報告）。何度実行しても安全。
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

PLACEHOLDERS = (
    "CERT_ID",
    "CERT_NAME",
    "VENDOR",
    "STUDY_GUIDE_URL",
    "EXAM_MINUTES",
    "PASS_SCORE",
    "MOCK_EXAMS",
    "QUESTIONS_PER_EXAM",
)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "exam-course"
_TOKEN = re.compile(r"\{\{([A-Z_]+)\}\}")
# テンプレート段階で置換せずコピーする拡張子
_COPY_AS_IS = (".csv",)


class InitError(Exception):
    """テンプレート展開に失敗した。"""


def render(text: str, values: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values:
            raise InitError(f"未知のプレースホルダ {{{{{key}}}}}")
        return str(values[key])

    return _TOKEN.sub(sub, text)


def _output_name(src: Path) -> str:
    name = src.name
    if name.endswith(".tmpl"):
        name = name[: -len(".tmpl")]
    if name == "gitignore":
        name = ".gitignore"
    return name


def init_course(
    dest, values: dict[str, str], template_dir=None
) -> dict[str, list[str]]:
    dest = Path(dest)
    tdir = Path(template_dir) if template_dir else TEMPLATE_DIR
    if not tdir.is_dir():
        raise InitError(f"テンプレートディレクトリが無い: {tdir}")
    missing = [k for k in PLACEHOLDERS if k not in values]
    if missing:
        raise InitError(f"値が渡されていないプレースホルダ: {missing}")

    dest.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    skipped: list[str] = []

    for src in sorted(tdir.iterdir()):
        if not src.is_file():
            continue
        out = dest / _output_name(src)
        if out.exists():
            skipped.append(out.name)
            continue
        if src.suffix in _COPY_AS_IS:
            shutil.copyfile(src, out)
        else:
            text = render(src.read_text(encoding="utf-8"), values)
            out.write_text(text, encoding="utf-8", newline="\n")
        created.append(out.name)

    return {"created": created, "skipped": skipped}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="試験対策講座プロジェクトを初期化する")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--cert", required=True, help="試験番号 (例: CCA-F)")
    ap.add_argument("--cert-name", required=True, help="正式名称")
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--study-guide", required=True)
    ap.add_argument("--exam-minutes", required=True)
    ap.add_argument("--pass-score", required=True)
    ap.add_argument("--mock-exams", default="6")
    ap.add_argument("--questions-per-exam", default="50")
    a = ap.parse_args(argv[1:])

    values = {
        "CERT_ID": a.cert,
        "CERT_NAME": a.cert_name,
        "VENDOR": a.vendor,
        "STUDY_GUIDE_URL": a.study_guide,
        "EXAM_MINUTES": a.exam_minutes,
        "PASS_SCORE": a.pass_score,
        "MOCK_EXAMS": a.mock_exams,
        "QUESTIONS_PER_EXAM": a.questions_per_exam,
    }
    try:
        result = init_course(a.dest, values)
    except InitError as e:
        print(f"FAIL: {e}")
        return 1

    for name in result["created"]:
        print(f"  created: {name}")
    for name in result["skipped"]:
        print(f"  skipped (already exists): {name}")
    print(f"OK: {len(result['created'])} created, {len(result['skipped'])} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

`plugins/udemy-exam-prep/templates/exam-course/sections.md.tmpl`:

```markdown
---
cert: {{CERT_ID}}
cert_name: {{CERT_NAME}}
vendor: {{VENDOR}}
study_guide: {{STUDY_GUIDE_URL}}
mode: mock-exam
exam:
  minutes: {{EXAM_MINUTES}}
  pass_score: {{PASS_SCORE}}
  max_score: 1000
  language: ja
mock_exams: {{MOCK_EXAMS}}
questions_per_exam: {{QUESTIONS_PER_EXAM}}
question_types:
  multiple-choice: "60-70%"
  multi-select: "30-40%"
scenario_ratio_min: "30%"
primary_sources: []
# domains は /udemy-exam-prep:create-sections が学習ガイドから確定させる。
# 形式: - {id: D1, name: ..., ratio: "27%", per_exam: 16}
---

# {{CERT_ID}} 演習テスト目次

> Source of Truth / 学習ガイド: {{STUDY_GUIDE_URL}}
> 試験概要: {{EXAM_MINUTES}}分 / 合格{{PASS_SCORE}} / フル模試{{MOCK_EXAMS}}本 x {{QUESTIONS_PER_EXAM}}問

## 試験ブループリント（トピックユニバース）

<!-- /udemy-exam-prep:create-sections が学習ガイドから起草する。
     ドメインごとにタスクステートメントとサブトピックを列挙し、
     front matter の domains と1対1で対応させる。 -->

## 配分表

<!-- create-sections が front matter の domains から生成する。 -->

## セクション一覧

<!-- create-sections が {{MOCK_EXAMS}} 本分の行を生成する。 -->
```

`plugins/udemy-exam-prep/templates/exam-course/question-bank.md.tmpl`:

```markdown
# Question Bank — {{MOCK_EXAMS}}本横断 出題済みインデックス

> 目的: 2本目以降の question-author が重複を回避するための参照テーブル。
> 更新ルール: exam-validator が各セクション検証後に追記する。
> 重複判定キー: (task_statement, tested_concept)。同一キーは**全{{MOCK_EXAMS}}本を通じて最大2回**まで、
> かつ同じ本の中では1回まで。2回出す場合はシナリオと問い方（根本原因の特定／最善の修正／
> アンチパターンの識別 など）を変える。

| section | q# | domain | task_statement | tested_concept | scenario | 問題文冒頭60字 |
|---|---|---|---|---|---|---|
```

`plugins/udemy-exam-prep/templates/exam-course/removed-questions.md.tmpl`:

```markdown
# 退避された問題

> exam-validator が検証で弾いた問題の保管場所。再利用候補として残す。
> 退避理由: シラバス外 / 重複 / 配分超過 / 品質不足

| 退避日 | 元section | domain | task_statement | 退避理由 | 問題文冒頭60字 |
|---|---|---|---|---|---|
```

`plugins/udemy-exam-prep/templates/exam-course/gitignore.tmpl`:

```gitignore
# ローカル固有設定（マシンごとに異なる権限設定。共有しない）
.claude/settings.local.json

# superpowers ランタイム作業ディレクトリ（プロジェクト成果物ではない）
.superpowers/

# シャッフル原本・中間ファイル（再生成可能。ローカルには残すが共有しない）
**/quiz.raw.csv
**/quiz.sample.csv
.skilltest/

# 一時スクリプト（エージェントの作業残骸が混入した場合の保険）
/*.py

# OS
Thumbs.db
.DS_Store
```

`plugins/udemy-exam-prep/templates/exam-course/PracticeTestBulkQuestionUploadTemplate_v2.csv`:
`C:\Users\nom40\Documents\Udemy\AI-103\PracticeTestBulkQuestionUploadTemplate_v2.csv` をそのままコピーする（17カラムのヘッダー行を含む参考ファイル）。

```bash
cp "/c/Users/nom40/Documents/Udemy/AI-103/PracticeTestBulkQuestionUploadTemplate_v2.csv" \
   "plugins/udemy-exam-prep/templates/exam-course/PracticeTestBulkQuestionUploadTemplate_v2.csv"
```

`plugins/udemy-exam-prep/templates/exam-course/CLAUDE.md.tmpl`:
AI-103 の `CLAUDE.md` を雛形化する。設計書 §7「`CLAUDE.md.tmpl` に継承する内容」の10項目をすべて含める。次の点を AI-103 版から変える。

1. 冒頭のプロジェクト概要を `{{CERT_ID}}` / `{{CERT_NAME}}` / `{{PASS_SCORE}}` / `{{EXAM_MINUTES}}` / `{{STUDY_GUIDE_URL}}` で雛形化
2. 構造方針を `{{MOCK_EXAMS}}` 本 x `{{QUESTIONS_PER_EXAM}}` 問で雛形化
3. ドメイン配分表は「`sections.md` の front matter `domains` が Source of Truth」と書き、表そのものは置かない
4. 「一次情報源」節は「`sections.md` front matter の `primary_sources` が Source of Truth。調査レシピは `research-cert-docs` スキル」とする
5. ディレクトリ構成図から `.claude/skills/` `.claude/agents/` を削除し、「harness は `udemy-exam-prep` プラグインが提供」と注記
6. 「ハーネス設計の意図」節を、harness がプラグインに移動した旨の説明に差し替え
7. エントリーポイント表の起動名をすべて `/udemy-exam-prep:<skill>` に変更し、`init-exam-course` の行を追加
8. クイズ作成ガイドラインの「#3 ドメイン配分ノルマ」を front matter 参照に、「#9 用語表記ルール」を資格非依存の一般則に書き換える
9. 技術的注意事項はそのまま維持（日本語 CSV は Python で書く / BOM 無し / MCP 名は環境依存 / Playwright はアクセシビリティツリー駆動）
10. レビュー断面 R1〜R4 の表はそのまま維持

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_init_course.py -v`
Expected: PASS（9 passed）

- [ ] **Step 5: Commit**

```bash
git add plugins/udemy-exam-prep/templates plugins/udemy-exam-prep/scripts/init_course.py tests/test_init_course.py
git commit -m "feat: 講座テンプレートと初期化スクリプト（冪等・上書きなし）"
```

---

### Task 4: quiz.csv の17カラム検証

**Files:**
- Create: `plugins/udemy-exam-prep/scripts/validate_quiz_csv.py`
- Test: `tests/test_validate_quiz_csv.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `HEADER: tuple[str, ...]` — 17カラムのヘッダー（Global Constraints の文字列と完全一致）
  - `read_rows(path) -> list[list[str]]` — `utf-8-sig` で読む
  - `validate_csv(path) -> list[str]` — 違反メッセージのリスト
  - `write_rows(path, rows: list[list[str]]) -> None` — `encoding='utf-8'`（BOM 無し）・`newline=''`・`QUOTE_MINIMAL` で書く。以降の全スクリプトは CSV 書き出しにこれを使う
  - CLI: `python plugins/udemy-exam-prep/scripts/validate_quiz_csv.py <quiz.csv> [<quiz.csv> ...]` → 全ファイル妥当なら exit 0
- 検証項目（AI-103 `quiz-csv-format` の規則を完全に踏襲）:
  1. BOM が無い
  2. ヘッダーが17カラムかつ文字列一致
  3. 全データ行が17カラム
  4. `Question Type` が `multiple-choice` / `multi-select`
  5. `multiple-choice` の正解はちょうど1個
  6. `multi-select` の正解は2個以上
  7. 正解番号が整数かつ存在する選択肢の範囲内
  8. `multi-select` は誤答を最低1つ持つ（正解数 < 選択肢数）
  9. 必須列（0,1,2,3,4,5,6,7,8,9,14,15,16）が空でない
  10. 選択肢テキストと解説テキストがペアで揃っている（選択肢が空なら解説も空、逆も不可）

- [ ] **Step 1: Write the failing test**

`tests/test_validate_quiz_csv.py`:

```python
from scripts.validate_quiz_csv import HEADER, read_rows, validate_csv, write_rows

def base_row():
    return [
        "What is the correct approach?", "multiple-choice",
        "Option A", "A is correct because ...",
        "Option B", "B is wrong because ...",
        "Option C", "C is wrong because ...",
        "Option D", "D is wrong because ...",
        "", "", "", "",
        "1", "A is correct. Source: https://example.com", "Domain 1",
    ]


def build(tmp_path, rows, *, bom=False, header=None):
    p = tmp_path / "quiz.csv"
    write_rows(p, [list(header or HEADER)] + rows)
    if bom:
        p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    return p


def test_header_is_17_columns():
    assert len(HEADER) == 17
    assert HEADER[0] == "Question"
    assert HEADER[-1] == "Domain"


def test_valid_file_passes(tmp_path):
    assert validate_csv(build(tmp_path, [base_row()])) == []


def test_write_rows_emits_no_bom(tmp_path):
    p = build(tmp_path, [base_row()])
    assert not p.read_bytes().startswith(b"\xef\xbb\xbf")


def test_write_rows_emits_no_blank_lines(tmp_path):
    p = build(tmp_path, [base_row(), base_row()])
    assert p.read_text(encoding="utf-8").count("\n\n") == 0


def test_round_trip_preserves_embedded_comma_and_quote(tmp_path):
    row = base_row()
    row[0] = 'He said "yes", then left'
    p = build(tmp_path, [row])
    assert validate_csv(p) == []
    assert read_rows(p)[1][0] == 'He said "yes", then left'


def test_bom_is_reported(tmp_path):
    errs = validate_csv(build(tmp_path, [base_row()], bom=True))
    assert any("BOM" in e for e in errs)


def test_bad_header_is_reported(tmp_path):
    bad = list(HEADER)
    bad[1] = "QuestionType"
    errs = validate_csv(build(tmp_path, [base_row()], header=bad))
    assert any("col 2" in e for e in errs)


def test_no_data_rows_is_reported(tmp_path):
    assert any("No data rows" in e for e in validate_csv(build(tmp_path, [])))


def test_invalid_question_type_is_reported(tmp_path):
    row = base_row()
    row[1] = "true-false"
    errs = validate_csv(build(tmp_path, [row]))
    assert any("invalid Question Type" in e for e in errs)


def test_multiple_choice_with_two_correct_is_reported(tmp_path):
    row = base_row()
    row[14] = "1,2"
    errs = validate_csv(build(tmp_path, [row]))
    assert any("multiple-choice" in e for e in errs)


def test_multi_select_with_one_correct_is_reported(tmp_path):
    row = base_row()
    row[1] = "multi-select"
    errs = validate_csv(build(tmp_path, [row]))
    assert any("must be" in e for e in errs)


def test_multi_select_without_distractor_is_reported(tmp_path):
    row = base_row()
    row[1] = "multi-select"
    row[14] = "1,2,3,4"
    errs = validate_csv(build(tmp_path, [row]))
    assert any("no distractor" in e for e in errs)


def test_correct_answer_out_of_range_is_reported(tmp_path):
    row = base_row()
    row[14] = "5"
    errs = validate_csv(build(tmp_path, [row]))
    assert any("out of range" in e for e in errs)


def test_empty_required_column_is_reported(tmp_path):
    row = base_row()
    row[15] = ""
    errs = validate_csv(build(tmp_path, [row]))
    assert any("column 16 is empty" in e for e in errs)


def test_option_without_explanation_is_reported(tmp_path):
    row = base_row()
    row[10] = "Option E"  # 選択肢だけ埋めて解説を空にする
    errs = validate_csv(build(tmp_path, [row]))
    assert any("option/explanation pair" in e for e in errs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate_quiz_csv.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.validate_quiz_csv'`

- [ ] **Step 3: Write minimal implementation**

`plugins/udemy-exam-prep/scripts/validate_quiz_csv.py`:

```python
"""Udemy Practice Test Bulk Upload Template v2（17カラム）の検証と安全な入出力。

1行でも形式逸脱があるとアップロードが全件失敗するため、quiz.csv を書いた直後に必ず通す。
CSV の読み書きは harness 全体でこのモジュールの read_rows / write_rows を使う。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

HEADER = (
    "Question", "Question Type",
    "Answer Option 1", "Explanation 1",
    "Answer Option 2", "Explanation 2",
    "Answer Option 3", "Explanation 3",
    "Answer Option 4", "Explanation 4",
    "Answer Option 5", "Explanation 5",
    "Answer Option 6", "Explanation 6",
    "Correct Answers", "Overall Explanation", "Domain",
)

REQUIRED_COLS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 14, 15, 16)
QUESTION_TYPES = ("multiple-choice", "multi-select")
# (選択肢, 解説) のカラム番号ペア
OPTION_PAIRS = tuple((2 + i * 2, 3 + i * 2) for i in range(6))

# Python の csv はフィールド長の上限に引っかかることがある（長い解説を書くため）
csv.field_size_limit(10_000_000)


def read_rows(path) -> list[list[str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def write_rows(path, rows: list[list[str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f, quoting=csv.QUOTE_MINIMAL).writerows(rows)


def correct_indices(cell: str) -> list[str]:
    return [c.strip() for c in cell.split(",") if c.strip()]


def validate_csv(path) -> list[str]:
    path = Path(path)
    errors: list[str] = []

    with open(path, "rb") as f:
        if f.read(3) == b"\xef\xbb\xbf":
            errors.append("BOM detected at file head — remove it")

    rows = read_rows(path)
    if len(rows) < 2:
        errors.append("No data rows")
        return errors

    header = rows[0]
    if len(header) != 17:
        errors.append(f"Header has {len(header)} columns, expected 17")
    for i, (got, want) in enumerate(zip(header, HEADER), 1):
        if got.strip() != want:
            errors.append(f'Header col {i}: got "{got}", expected "{want}"')

    for i, row in enumerate(rows[1:], 2):
        if len(row) != 17:
            errors.append(f"Row {i}: has {len(row)} columns, expected 17")
            continue

        qt = row[1].strip()
        if qt not in QUESTION_TYPES:
            errors.append(f'Row {i}: invalid Question Type "{qt}"')

        nopt = sum(1 for opt, _ in OPTION_PAIRS if row[opt].strip())
        correct = correct_indices(row[14])

        if qt == "multiple-choice" and len(correct) != 1:
            errors.append(
                f"Row {i}: multiple-choice with {len(correct)} correct answers "
                "— must be exactly 1"
            )
        if qt == "multi-select" and len(correct) < 2:
            errors.append(
                f"Row {i}: multi-select with {len(correct)} correct answer(s) "
                "— must be >=2 or change to multiple-choice"
            )
        if qt == "multi-select" and correct and len(correct) >= nopt:
            errors.append(
                f"Row {i}: multi-select with no distractor — {len(correct)} correct "
                f"of {nopt} options (need at least 1 incorrect)"
            )
        for c in correct:
            if not c.isdigit() or not (1 <= int(c) <= nopt):
                errors.append(
                    f'Row {i}: correct answer "{c}" out of range '
                    f"— only {nopt} option(s) present"
                )

        for col in REQUIRED_COLS:
            if not row[col].strip():
                errors.append(f"Row {i}: column {col + 1} is empty (required)")

        for opt, exp in OPTION_PAIRS:
            if bool(row[opt].strip()) != bool(row[exp].strip()):
                errors.append(
                    f"Row {i}: broken option/explanation pair at columns "
                    f"{opt + 1}/{exp + 1}"
                )

    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: validate_quiz_csv.py <quiz.csv> [...]", file=sys.stderr)
        return 2
    failed = False
    for target in argv[1:]:
        errors = validate_csv(target)
        if errors:
            failed = True
            print(f"FAIL {target}: {len(errors)} error(s)")
            for e in errors[:20]:
                print(f"  - {e}")
            if len(errors) > 20:
                print(f"  ... and {len(errors) - 20} more")
        else:
            n = len(read_rows(target)) - 1
            print(f"OK   {target}: {n} questions, all valid")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate_quiz_csv.py -v`
Expected: PASS（15 passed）

- [ ] **Step 5: Commit**

```bash
git add plugins/udemy-exam-prep/scripts/validate_quiz_csv.py tests/test_validate_quiz_csv.py
git commit -m "feat: quiz.csv の17カラム検証と BOM 無し入出力"
```

---

### Task 5: 選択肢の決定的シャッフルと正解位置分布の検証

**Files:**
- Create: `plugins/udemy-exam-prep/scripts/shuffle_options.py`
- Test: `tests/test_shuffle_options.py`

**Interfaces:**
- Consumes: Task 4 の `scripts.validate_quiz_csv`（`HEADER` / `read_rows` / `write_rows` / `OPTION_PAIRS` / `correct_indices`）
- Produces:
  - `shuffle_row(row: list[str], rng: random.Random) -> list[str]` — 1行の選択肢と解説をペアのまま入れ替え、`Correct Answers` を新しい位置に振り直す
  - `shuffle_file(path, seed: int = 42) -> dict` — ファイル全体をシャッフルして上書きし、`{"n": 問題数, "distribution": {"1": 件数, ...}}` を返す
  - `position_distribution(rows: list[list[str]]) -> dict[str, int]` — `multiple-choice` の正解位置のヒストグラム
  - `distribution_warnings(dist: dict[str, int], n_mc: int, tolerance: float = 0.15) -> list[str]` — どれかの位置が期待比率から `tolerance` 以上ずれていたら警告文を返す
  - CLI: `python plugins/udemy-exam-prep/scripts/shuffle_options.py <quiz.csv> [--seed 42]`
- 不変条件: シャッフル後も (選択肢テキスト, その解説) の対応が壊れない。正解の**集合**が保たれる。空の選択肢ペアは末尾に残る

- [ ] **Step 1: Write the failing test**

`tests/test_shuffle_options.py`:

```python
import random
from scripts.shuffle_options import (
    distribution_warnings, position_distribution, shuffle_file, shuffle_row,
)
from scripts.validate_quiz_csv import HEADER, read_rows, validate_csv, write_rows


def row(correct="1", qt="multiple-choice", nopt=4):
    r = ["Q?", qt]
    for i in range(6):
        if i < nopt:
            r += [f"OPT{i + 1}", f"EXP{i + 1}"]
        else:
            r += ["", ""]
    r += [correct, "overall", "Domain 1"]
    return r


def test_shuffle_keeps_option_explanation_pairs():
    out = shuffle_row(row(), random.Random(1))
    for opt, exp in ((2, 3), (4, 5), (6, 7), (8, 9)):
        assert out[opt].replace("OPT", "") == out[exp].replace("EXP", "")


def test_shuffle_moves_correct_answer_to_its_new_position():
    out = shuffle_row(row(correct="1"), random.Random(1))
    idx = int(out[14])
    assert out[2 + (idx - 1) * 2] == "OPT1"


def test_shuffle_preserves_multi_select_correct_set():
    out = shuffle_row(row(correct="1,3", qt="multi-select"), random.Random(7))
    moved = {out[2 + (int(i) - 1) * 2] for i in out[14].split(",")}
    assert moved == {"OPT1", "OPT3"}


def test_shuffle_keeps_empty_pairs_at_the_end():
    out = shuffle_row(row(nopt=4), random.Random(3))
    assert out[10:14] == ["", "", "", ""]


def test_shuffle_is_deterministic_for_a_fixed_seed():
    a = shuffle_row(row(), random.Random(42))
    b = shuffle_row(row(), random.Random(42))
    assert a == b


def test_shuffle_file_output_still_validates(tmp_path):
    p = tmp_path / "quiz.csv"
    write_rows(p, [list(HEADER)] + [row(correct=str(i % 4 + 1)) for i in range(20)])
    result = shuffle_file(p, seed=42)
    assert result["n"] == 20
    assert validate_csv(p) == []


def test_shuffle_file_is_reproducible(tmp_path):
    def make():
        p = tmp_path / f"q{make.i}.csv"
        make.i += 1
        write_rows(p, [list(HEADER)] + [row(correct="1") for _ in range(10)])
        shuffle_file(p, seed=42)
        return read_rows(p)
    make.i = 0
    assert make() == make()


def test_position_distribution_counts_only_multiple_choice():
    rows = [list(HEADER), row(correct="2"), row(correct="2"),
            row(correct="1,2", qt="multi-select")]
    assert position_distribution(rows) == {"2": 2}


def test_distribution_warnings_flags_a_skewed_spread():
    assert distribution_warnings({"1": 40, "2": 0, "3": 0, "4": 0}, 40)


def test_distribution_warnings_accepts_an_even_spread():
    assert distribution_warnings({"1": 10, "2": 10, "3": 10, "4": 10}, 40) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_shuffle_options.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.shuffle_options'`

- [ ] **Step 3: Write minimal implementation**

`plugins/udemy-exam-prep/scripts/shuffle_options.py`:

```python
"""選択肢の位置バイアスを消すための決定的シャッフルと正解位置分布の検証。

question-author は「正解を選択肢1に置きがち」なので、生成直後に必ず通す。
seed 固定なので同じ入力からは常に同じ出力になる（再実行で差分が暴れない）。
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

from scripts.validate_quiz_csv import (
    OPTION_PAIRS, correct_indices, read_rows, write_rows,
)


def shuffle_row(row: list[str], rng: random.Random) -> list[str]:
    out = list(row)
    filled = [(row[o], row[e]) for o, e in OPTION_PAIRS if row[o].strip()]
    n = len(filled)
    if n < 2:
        return out

    correct_old = {int(c) for c in correct_indices(row[14]) if c.isdigit()}
    order = list(range(n))
    rng.shuffle(order)

    for new_pos, old_pos in enumerate(order):
        opt_col, exp_col = OPTION_PAIRS[new_pos]
        out[opt_col], out[exp_col] = filled[old_pos]
    for pos in range(n, len(OPTION_PAIRS)):
        opt_col, exp_col = OPTION_PAIRS[pos]
        out[opt_col], out[exp_col] = "", ""

    new_correct = sorted(
        new_pos + 1 for new_pos, old_pos in enumerate(order)
        if (old_pos + 1) in correct_old
    )
    out[14] = ",".join(str(c) for c in new_correct)
    return out


def position_distribution(rows: list[list[str]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows[1:]:
        if len(row) == 17 and row[1].strip() == "multiple-choice":
            counter[row[14].strip()] += 1
    return dict(counter)


def distribution_warnings(
    dist: dict[str, int], n_mc: int, tolerance: float = 0.15
) -> list[str]:
    if n_mc == 0:
        return []
    positions = sorted(dist) or ["1"]
    expected = 1 / max(len(positions), 2)
    warnings: list[str] = []
    for pos in positions:
        share = dist.get(pos, 0) / n_mc
        if abs(share - expected) > tolerance:
            warnings.append(
                f"correct-answer position {pos}: {dist.get(pos, 0)}/{n_mc} "
                f"({share:.0%}) deviates from the expected {expected:.0%}"
            )
    return warnings


def shuffle_file(path, seed: int = 42) -> dict:
    rows = read_rows(path)
    rng = random.Random(seed)
    shuffled = [rows[0]] + [
        shuffle_row(r, rng) if len(r) == 17 else r for r in rows[1:]
    ]
    write_rows(path, shuffled)
    dist = position_distribution(shuffled)
    n_mc = sum(dist.values())
    return {
        "n": len(shuffled) - 1,
        "distribution": dist,
        "warnings": distribution_warnings(dist, n_mc),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="quiz.csv の選択肢を決定的にシャッフルする")
    ap.add_argument("csv_path")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv[1:])

    result = shuffle_file(a.csv_path, seed=a.seed)
    print(f"shuffled {result['n']} questions (seed={a.seed})")
    print(f"correct-answer position distribution: {result['distribution']}")
    for w in result["warnings"]:
        print(f"  WARN: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_shuffle_options.py -v`
Expected: PASS（10 passed）

- [ ] **Step 5: Commit**

```bash
git add plugins/udemy-exam-prep/scripts/shuffle_options.py tests/test_shuffle_options.py
git commit -m "feat: 選択肢の決定的シャッフルと正解位置分布の検証"
```

---

### Task 6: ドメイン配分・シラバス整合・重複の検証

**Files:**
- Create: `plugins/udemy-exam-prep/scripts/validate_exam.py`
- Test: `tests/test_validate_exam.py`

**Interfaces:**
- Consumes: Task 2 の `scripts.profile`（`load_profile` / `domain_quota` / `domain_names`）、Task 4 の `scripts.validate_quiz_csv`（`read_rows`）
- Produces:
  - `domain_counts(rows: list[list[str]]) -> dict[str, int]` — `Domain` 列（正式名）の出現数
  - `check_quota(rows, profile) -> list[str]` — ノルマとの差分。`Domain` 列が `domains[].name` のいずれとも一致しない場合も報告
  - `parse_question_bank(path) -> list[dict]` — `question-bank.md` の表を読み `section` / `q` / `domain` / `task_statement` / `tested_concept` / `scenario` / `head` のキーを持つ dict のリストにする。ファイルが無ければ空リスト
  - `check_duplicates(entries: list[dict], max_per_concept: int = 2) -> list[str]` — 同一 `(task_statement, tested_concept)` が `max_per_concept` 回を超える／同一 section 内で重複する／複数回出現なのに `scenario` が同じ、の3条件を報告
  - 上限は `sections.md` front matter の**任意キー `max_per_concept`（既定 2）**で上書きできる。CLI は `profile.get("max_per_concept", 2)` を読んで `check_duplicates` に渡す（問題総数がタスクステートメントの概念数に対して多い資格では 3 にする）
  - `bank_rows(entries: list[dict]) -> list[str]` — `question-bank.md` に追記する Markdown 行を生成
  - CLI: `python plugins/udemy-exam-prep/scripts/validate_exam.py --sections <sections.md> --bank <question-bank.md> <quiz.csv> [...]`
- `Domain` 列には `domains[].name` の値をそのまま書く（`D1` のような ID ではない）

- [ ] **Step 1: Write the failing test**

`tests/test_validate_exam.py`:

```python
import textwrap
from scripts.validate_exam import (
    bank_rows, check_duplicates, check_quota, domain_counts, parse_question_bank,
)
from scripts.validate_quiz_csv import HEADER

PROFILE = {
    "questions_per_exam": 4,
    "mock_exams": 2,
    "domains": [
        {"id": "D1", "name": "Alpha", "ratio": "50%", "per_exam": 2},
        {"id": "D2", "name": "Beta", "ratio": "50%", "per_exam": 2},
    ],
}


def row(domain):
    r = ["Q?", "multiple-choice"]
    for i in range(6):
        r += ([f"OPT{i + 1}", f"EXP{i + 1}"] if i < 4 else ["", ""])
    return r + ["1", "overall", domain]


def test_domain_counts():
    rows = [list(HEADER), row("Alpha"), row("Alpha"), row("Beta")]
    assert domain_counts(rows) == {"Alpha": 2, "Beta": 1}


def test_check_quota_passes_when_counts_match():
    rows = [list(HEADER), row("Alpha"), row("Alpha"), row("Beta"), row("Beta")]
    assert check_quota(rows, PROFILE) == []


def test_check_quota_reports_a_shortfall():
    rows = [list(HEADER), row("Alpha"), row("Beta"), row("Beta"), row("Beta")]
    errs = check_quota(rows, PROFILE)
    assert any("Alpha" in e and "1" in e and "2" in e for e in errs)


def test_check_quota_reports_an_unknown_domain():
    rows = [list(HEADER), row("Gamma"), row("Alpha"), row("Beta"), row("Beta")]
    assert any("Gamma" in e for e in check_quota(rows, PROFILE))


BANK = textwrap.dedent("""\
    # Question Bank

    | section | q# | domain | task_statement | tested_concept | scenario | head |
    |---|---|---|---|---|---|---|
    | section01 | Q1 | D1 | 1.1 | stop_reason loop control | S1 | Your agent ... |
    | section01 | Q2 | D2 | 2.1 | tool description quality | S1 | Both tools ... |
    | section02 | Q1 | D1 | 1.1 | stop_reason loop control | S3 | The loop ... |
    """)


def test_parse_question_bank(tmp_path):
    p = tmp_path / "question-bank.md"
    p.write_text(BANK, encoding="utf-8")
    entries = parse_question_bank(p)
    assert len(entries) == 3
    assert entries[0]["task_statement"] == "1.1"
    assert entries[2]["scenario"] == "S3"


def test_parse_question_bank_returns_empty_when_absent(tmp_path):
    assert parse_question_bank(tmp_path / "nope.md") == []


def test_check_duplicates_allows_two_uses_in_different_scenarios(tmp_path):
    p = tmp_path / "question-bank.md"
    p.write_text(BANK, encoding="utf-8")
    assert check_duplicates(parse_question_bank(p)) == []


def test_check_duplicates_reports_a_third_use():
    entries = [
        {"section": f"section0{i}", "q": "Q1", "domain": "D1",
         "task_statement": "1.1", "tested_concept": "same concept",
         "scenario": f"S{i}", "head": "..."}
        for i in (1, 2, 3)
    ]
    assert any("3 times" in e for e in check_duplicates(entries))


def test_check_duplicates_honors_a_raised_cap():
    entries = [
        {"section": f"section0{i}", "q": "Q1", "domain": "D1",
         "task_statement": "1.1", "tested_concept": "same concept",
         "scenario": f"S{i}", "head": "..."}
        for i in (1, 2, 3)
    ]
    assert check_duplicates(entries, max_per_concept=3) == []


def test_check_duplicates_reports_same_section_repeat():
    entries = [
        {"section": "section01", "q": q, "domain": "D1",
         "task_statement": "1.1", "tested_concept": "same concept",
         "scenario": "S1", "head": "..."}
        for q in ("Q1", "Q2")
    ]
    assert any("same section" in e for e in check_duplicates(entries))


def test_check_duplicates_reports_same_scenario_reuse():
    entries = [
        {"section": f"section0{i}", "q": "Q1", "domain": "D1",
         "task_statement": "1.1", "tested_concept": "same concept",
         "scenario": "S1", "head": "..."}
        for i in (1, 2)
    ]
    assert any("same scenario" in e for e in check_duplicates(entries))


def test_bank_rows_emits_pipe_table_rows():
    entries = [{"section": "section01", "q": "Q1", "domain": "D1",
                "task_statement": "1.1", "tested_concept": "c",
                "scenario": "S1", "head": "h"}]
    line = bank_rows(entries)[0]
    assert line.startswith("| section01 | Q1 | D1 | 1.1 | c | S1 | h |")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate_exam.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.validate_exam'`

- [ ] **Step 3: Write minimal implementation**

`plugins/udemy-exam-prep/scripts/validate_exam.py`:

```python
"""フル模試の成立条件を検証する: ドメイン配分・シラバス整合・本横断の重複。

exam-validator エージェントが呼ぶ。判定ロジックをここに置くことで、
エージェントの出力揺れに関係なく同じ基準が適用される。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

from scripts.profile import domain_names, domain_quota, load_profile
from scripts.validate_quiz_csv import read_rows

BANK_FIELDS = (
    "section", "q", "domain", "task_statement", "tested_concept", "scenario", "head",
)


def domain_counts(rows: list[list[str]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows[1:]:
        if len(row) == 17 and row[16].strip():
            counter[row[16].strip()] += 1
    return dict(counter)


def check_quota(rows: list[list[str]], profile: dict) -> list[str]:
    counts = domain_counts(rows)
    names = domain_names(profile)
    quota = domain_quota(profile)
    name_to_id = {v: k for k, v in names.items()}

    errors: list[str] = []
    for name in counts:
        if name not in name_to_id:
            errors.append(
                f'unknown Domain value "{name}" — must be one of {sorted(name_to_id)}'
            )
    for did, want in quota.items():
        got = counts.get(names[did], 0)
        if got != want:
            errors.append(f'{did} "{names[did]}": {got} questions, expected {want}')

    total = sum(counts.values())
    want_total = profile.get("questions_per_exam")
    if want_total is not None and total != want_total:
        errors.append(f"total {total} questions, expected {want_total}")
    return errors


def parse_question_bank(path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(BANK_FIELDS):
            continue
        if cells[0] in ("section", "---") or set(cells[0]) <= {"-", ":"}:
            continue
        entries.append(dict(zip(BANK_FIELDS, cells)))
    return entries


def check_duplicates(entries: list[dict], max_per_concept: int = 2) -> list[str]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in entries:
        grouped[(e["task_statement"], e["tested_concept"])].append(e)

    errors: list[str] = []
    for (ts, concept), group in sorted(grouped.items()):
        label = f'({ts}, "{concept}")'
        if len(group) > max_per_concept:
            where = ", ".join(f"{g['section']}/{g['q']}" for g in group)
            errors.append(
                f"{label} used {len(group)} times (max {max_per_concept}): {where}"
            )
        sections = [g["section"] for g in group]
        for section, n in Counter(sections).items():
            if n > 1:
                errors.append(f"{label} repeated {n} times in the same section {section}")
        scenarios = [g["scenario"] for g in group]
        for scenario, n in Counter(scenarios).items():
            if n > 1:
                errors.append(
                    f"{label} reused in the same scenario {scenario} {n} times "
                    "— vary the scenario when reusing a concept"
                )
    return errors


def bank_rows(entries: list[dict]) -> list[str]:
    return [
        "| " + " | ".join(e[f].replace("|", "/") for f in BANK_FIELDS) + " |"
        for e in entries
    ]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="フル模試の配分・整合・重複を検証する")
    ap.add_argument("--sections", required=True)
    ap.add_argument("--bank")
    ap.add_argument("csv_paths", nargs="+")
    a = ap.parse_args(argv[1:])

    profile = load_profile(a.sections)
    failed = False

    for target in a.csv_paths:
        errors = check_quota(read_rows(target), profile)
        if errors:
            failed = True
            print(f"FAIL {target}: {len(errors)} quota/syllabus error(s)")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"OK   {target}: domain quota satisfied")

    if a.bank:
        cap = profile.get("max_per_concept", 2)
        errors = check_duplicates(parse_question_bank(a.bank), max_per_concept=cap)
        if errors:
            failed = True
            print(f"FAIL {a.bank}: {len(errors)} duplication error(s)")
            for e in errors[:20]:
                print(f"  - {e}")
            if len(errors) > 20:
                print(f"  ... and {len(errors) - 20} more")
        else:
            print(f"OK   {a.bank}: no duplication violations")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate_exam.py -v`
Expected: PASS（13 passed）

- [ ] **Step 5: Run the whole suite and commit**

Run: `python -m pytest -v`
Expected: PASS（合計 62 passed）

```bash
git add plugins/udemy-exam-prep/scripts/validate_exam.py tests/test_validate_exam.py
git commit -m "feat: ドメイン配分・シラバス整合・本横断重複の検証"
```

---

### Task 7: スキル8個の移植と汎用化

**Files:**
- Create: `plugins/udemy-exam-prep/skills/init-exam-course/SKILL.md`（新規）
- Create: `plugins/udemy-exam-prep/skills/create-sections/SKILL.md`（移植＋汎用化）
- Create: `plugins/udemy-exam-prep/skills/create-section/SKILL.md`（移植＋汎用化）
- Create: `plugins/udemy-exam-prep/skills/create-udemy-course/SKILL.md`（移植＋汎用化）
- Create: `plugins/udemy-exam-prep/skills/upload-practice-tests/SKILL.md`（移植）
- Create: `plugins/udemy-exam-prep/skills/quiz-csv-format/SKILL.md`（移植＋スクリプト参照化）
- Create: `plugins/udemy-exam-prep/skills/research-cert-docs/SKILL.md`（移植＋ベンダー表拡張）
- Create: `plugins/udemy-exam-prep/skills/udemy-bulk-upload/SKILL.md`（移植）
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: Task 2–6 の全スクリプト。スキル本文は Python を再掲せず `python "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" ...` の形で呼ぶ
- Produces: スキル名8個（`init-exam-course` / `create-sections` / `create-section` / `create-udemy-course` / `upload-practice-tests` / `quiz-csv-format` / `research-cert-docs` / `udemy-bulk-upload`）。以降 Task 8 のエージェント本文がこれらを `[[skill-name]]` で参照する
- 移植元: `C:\Users\nom40\Documents\Udemy\AI-103\.claude\skills\<name>\SKILL.md`

- [ ] **Step 1: Write the failing test**

`tests/test_skills.py`:

```python
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "udemy-exam-prep"
SKILLS = PLUGIN / "skills"

EXPECTED = {
    "init-exam-course", "create-sections", "create-section", "create-udemy-course",
    "upload-practice-tests", "quiz-csv-format", "research-cert-docs",
    "udemy-bulk-upload",
}
# 汎用化したのに資格固有語が残っていたら退行
FORBIDDEN = ("AI-103", "Foundry", "Azure AI", "Microsoft Learn が一次情報源")


def skill_files():
    return sorted(SKILLS.glob("*/SKILL.md"))


def front_matter(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].strip() == "---", f"{path}: front matter がない"
    end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
    return "\n".join(lines[1:end])


def test_all_expected_skills_exist():
    assert {p.parent.name for p in skill_files()} == EXPECTED


def test_every_skill_has_name_and_description():
    for p in skill_files():
        fm = front_matter(p)
        assert re.search(r"^name:\s*\S+", fm, re.M), p
        assert re.search(r"^description:\s*\S+", fm, re.M), p


def test_skill_name_matches_its_directory():
    for p in skill_files():
        name = re.search(r"^name:\s*(\S+)", front_matter(p), re.M).group(1)
        assert name == p.parent.name, p


def test_no_cert_specific_leftovers():
    for p in skill_files():
        text = p.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            assert token not in text, f"{p}: 資格固有語 '{token}' が残っている"


def test_scripts_are_called_through_plugin_root():
    """スキルは Python を再掲せず CLAUDE_PLUGIN_ROOT 経由でスクリプトを呼ぶ。"""
    callers = {
        "quiz-csv-format": "validate_quiz_csv.py",
        "create-section": "shuffle_options.py",
        "init-exam-course": "init_course.py",
        "create-sections": "profile.py",
    }
    for skill, script in callers.items():
        text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "${CLAUDE_PLUGIN_ROOT}" in text, skill
        assert script in text, f"{skill} が {script} を呼んでいない"


def test_entrypoint_skills_document_the_namespaced_invocation():
    for skill in ("init-exam-course", "create-sections", "create-section",
                  "create-udemy-course", "upload-practice-tests"):
        text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert f"/udemy-exam-prep:{skill}" in text, skill


def test_research_skill_lists_every_supported_vendor():
    text = (SKILLS / "research-cert-docs" / "SKILL.md").read_text(encoding="utf-8")
    for vendor in ("anthropic", "microsoft", "github", "cloudflare", "ipa", "generic"):
        assert vendor in text, vendor
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skills.py -v`
Expected: FAIL — `skills/*/SKILL.md` が存在せず `test_all_expected_skills_exist` が空集合で落ちる

- [ ] **Step 3: Write the skills**

移植の手順（1スキルずつ実施する）:

1. 移植元を読む: `cat "/c/Users/nom40/Documents/Udemy/AI-103/.claude/skills/<name>/SKILL.md"`
2. front matter の `name` / `description` を維持（`description` から `AI-103` を除き、資格非依存の言い方にする）
3. 本文の資格固有記述を front matter 参照に置換
4. 埋め込み Python を削除し `python "${CLAUDE_PLUGIN_ROOT}/scripts/<script>.py"` の呼び出しに置換
5. 起動例を `/udemy-exam-prep:<name>` に変更

スキルごとの必須変更点:

**`init-exam-course`（新規）** — 次の内容で書く。
- 起動例: `/udemy-exam-prep:init-exam-course CCA-F`
- 引数から `CERT_ID` を取り、残り7項目をユーザーにヒアリングする（既定値: `MOCK_EXAMS=6` / `QUESTIONS_PER_EXAM=50`）。`VENDOR` は `anthropic` / `microsoft` / `github` / `cloudflare` / `ipa` / `generic` から選ばせる
- 収集した値で次を実行する:
  ```bash
  python "${CLAUDE_PLUGIN_ROOT}/scripts/init_course.py" \
    --dest . --cert "<CERT_ID>" --cert-name "<CERT_NAME>" --vendor "<VENDOR>" \
    --study-guide "<STUDY_GUIDE_URL>" --exam-minutes <N> --pass-score <N> \
    --mock-exams <N> --questions-per-exam <N>
  ```
- created / skipped の一覧をそのまま提示し、次アクション `/udemy-exam-prep:create-sections <CERT_ID>` を案内する
- 既存ファイルは skip されるだけで上書きされないことを明記する

**`create-sections`** — `AI-103` 6箇所を除去。次を追加する。
- 引数: `<試験番号> [学習ガイドURL]`（URL 省略時は front matter の `study_guide` を使う）
- 学習ガイドから抽出したドメインとサブトピックで **front matter の `domains` と `primary_sources` を確定**させる
- R1 レビュー前に必ず検証を通す:
  ```bash
  python "${CLAUDE_PLUGIN_ROOT}/scripts/profile.py" sections.md
  ```
- R1 の確認項目に「front matter 検証5項目」を追加する（必須キー／`per_exam` 合計＝`questions_per_exam`／`id` 一意／`mode`／`mock_exams`・`questions_per_exam` ≥1）

**`create-section`** — `AI-103` 1箇所を除去。`questions_per_exam` と `domains` を front matter から読む。シャッフル手順を次に置換する。
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/shuffle_options.py" "sectionNN-mock-exam-N/quiz.csv" --seed 42
```
検証手順を次に置換する。
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_quiz_csv.py" "sectionNN-mock-exam-N/quiz.csv"
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_exam.py" --sections sections.md \
  --bank question-bank.md "sectionNN-mock-exam-N/quiz.csv"
```

**`create-udemy-course`** — `AI-103` 3箇所を除去。コース情報を front matter（`cert` / `cert_name` / `cert_name_ja` / `credential_url` / `exam` / `mock_exams` / `questions_per_exam`）とプロジェクト `CLAUDE.md` から組み立てる。

**`quiz-csv-format`** — 17カラム仕様表・厳守ルール6項目・安全な書き出しパターンは維持。`Domain` 列の説明を「`sections.md` の `domains[].name` の値をそのまま書く」に変更。埋め込み検証 Python（63–129行）を削除し次に置換する。
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_quiz_csv.py" <quiz.csv>
```
CSV の読み書きは `scripts/validate_quiz_csv.py` の `read_rows` / `write_rows` を使うと明記する。

**`research-cert-docs`** — 「ステップ1: 資格の種類を判定」を front matter の `vendor` 参照に置換し、ベンダー別レシピ表を6行で持つ。

| vendor | 優先1 | 優先2 | 優先3 |
|---|---|---|---|
| `anthropic` | 公式 Exam Guide PDF（プロジェクト内に保存したもの） | `docs.claude.com` を WebFetch（Claude Code / Agent SDK / API / MCP） | `modelcontextprotocol.io` を WebFetch |
| `microsoft` | `microsoft_docs_search` / `microsoft_docs_fetch`（MCP） | context7 `query-docs`（関連 SDK） | WebFetch（`learn.microsoft.com/search/?terms=`） |
| `github` | WebFetch（`docs.github.com`） | context7 `query-docs` | WebSearch |
| `cloudflare` | `search_cloudflare_documentation`（MCP） | WebFetch（`developers.cloudflare.com`） | context7 `query-docs` |
| `ipa` | WebFetch（`www.ipa.go.jp` のシラバス・過去問 PDF） | WebSearch | — |
| `generic` | WebSearch で公式ドメインを特定 → WebFetch | context7 `query-docs` | — |

未知の `vendor` は `generic` 行で動作させ、警告を出す。`sources.md` のフォーマット定義はこのスキルが唯一の定義元として維持する。二次情報（個人ブログ・受験記）は**難易度校正の参考にのみ使い、問題の出典には使わない**と明記する。

**`upload-practice-tests`** — 変更なしで移植。テスト設定値を「制限時間＝front matter の `exam.minutes` そのまま／合格ライン 70%／質問のランダム化 ON」と明記。CSV 事前検証を `scripts/validate_quiz_csv.py` 呼び出しに置換。

**`udemy-bulk-upload`** — 変更なしで移植。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skills.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add plugins/udemy-exam-prep/skills tests/test_skills.py
git commit -m "feat: スキル8個を移植・汎用化しスクリプト呼び出しに統一"
```

---

### Task 8: エージェント3個の移植と汎用化

**Files:**
- Create: `plugins/udemy-exam-prep/agents/doc-researcher.md`
- Create: `plugins/udemy-exam-prep/agents/question-author.md`
- Create: `plugins/udemy-exam-prep/agents/exam-validator.md`
- Test: `tests/test_agents.py`

**Interfaces:**
- Consumes: Task 7 のスキル名（本文から `[[skill-name]]` で参照する）、Task 2–6 のスクリプト
- Produces: エージェント名3個。`create-section` / `create-sections` スキルがこの名前で起動する
- 移植元: `C:\Users\nom40\Documents\Udemy\AI-103\.claude\agents\<name>.md`
- `tools:` の MCP ツール名は環境依存のため、`doc-researcher` では `WebFetch` / `WebSearch` / `Read` / `Grep` / `Glob` / `Bash` を基本とし、MCP ツールは本文で機能名（`microsoft_docs_search` 等）として言及する

- [ ] **Step 1: Write the failing test**

`tests/test_agents.py`:

```python
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "udemy-exam-prep"
AGENTS = PLUGIN / "agents"

EXPECTED = {"doc-researcher", "question-author", "exam-validator"}
FORBIDDEN = ("AI-103", "Foundry", "Azure AI", "D1〜D5", "D1=14")


def agent_files():
    return sorted(AGENTS.glob("*.md"))


def front_matter(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].strip() == "---", f"{path}: front matter がない"
    end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
    return "\n".join(lines[1:end])


def test_all_expected_agents_exist():
    assert {p.stem for p in agent_files()} == EXPECTED


def test_every_agent_declares_name_description_tools_model():
    for p in agent_files():
        fm = front_matter(p)
        for key in ("name", "description", "tools", "model"):
            assert re.search(rf"^{key}:\s*\S+", fm, re.M), f"{p}: {key} がない"


def test_agent_name_matches_filename():
    for p in agent_files():
        name = re.search(r"^name:\s*(\S+)", front_matter(p), re.M).group(1)
        assert name == p.stem, p


def test_no_cert_specific_leftovers():
    for p in agent_files():
        text = p.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            assert token not in text, f"{p}: 資格固有語 '{token}' が残っている"


def test_question_author_defers_csv_rules_to_the_skill():
    text = (AGENTS / "question-author.md").read_text(encoding="utf-8")
    assert "[[quiz-csv-format]]" in text
    # 17カラムの規約を再掲していない（定義元は quiz-csv-format ただ1つ）
    assert "Answer Option 5" not in text


def test_exam_validator_uses_the_validation_scripts():
    text = (AGENTS / "exam-validator.md").read_text(encoding="utf-8")
    assert "${CLAUDE_PLUGIN_ROOT}" in text
    assert "validate_exam.py" in text
    assert "validate_quiz_csv.py" in text


def test_doc_researcher_defers_source_priority_to_the_skill():
    text = (AGENTS / "doc-researcher.md").read_text(encoding="utf-8")
    assert "[[research-cert-docs]]" in text
    assert "primary_sources" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents.py -v`
Expected: FAIL — `agents/*.md` が存在せず `test_all_expected_agents_exist` が空集合で落ちる

- [ ] **Step 3: Write the agents**

移植元を読んでから、エージェントごとに次を変更する。

**`doc-researcher`** — 情報源の選択を front matter の `primary_sources`（`priority` 昇順）に従わせる。ベンダー別のツール選択は `[[research-cert-docs]]` を参照し再掲しない。`tools:` は `WebFetch, WebSearch, Read, Grep, Glob, Bash`、`model: sonnet`。返す digest の形式（事実リスト＋URL）は維持する。

**`question-author`** — `AI-103` 5箇所と語彙リストを除去。次に置き換える。
- 出題ノルマ・問題数・出題形式比率・シナリオ比率は**呼び出し元から渡される**（front matter 由来）
- 用語表記ルールはプロジェクト `CLAUDE.md`「用語表記ルール」に従う
- CSV 規約は `[[quiz-csv-format]]` に従い再掲しない
- `Domain` 列には `sections.md` の `domains[].name` の値をそのまま書く
- 各問題について `task_statement` と `tested_concept` を必ず申告する（`question-bank.md` の重複判定キーになる）
- 解説スタイル（正解の理由＋不正解選択肢が何を意味しどこが違うか＋出典URL）は維持する

**`exam-validator`** — ドメイン固定を撤廃。検証を次のスクリプト呼び出しで行う。
```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_quiz_csv.py" "<quiz.csv>"
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_exam.py" --sections sections.md \
  --bank question-bank.md "<quiz.csv>"
```
スクリプトが報告した違反に対して、退避（`removed-questions.md` へ移動）と `question-bank.md` への追記を行う責務は維持する。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add plugins/udemy-exam-prep/agents tests/test_agents.py
git commit -m "feat: エージェント3個を移植・汎用化し検証をスクリプトに委譲"
```

---

### Task 9: プラグイン README、スモークテスト、GitHub 公開

**Files:**
- Create: `plugins/udemy-exam-prep/README.md`
- Modify: `README.md`（マーケットプレイス側。プラグイン表に説明を補う）
- Test: 手動スモークテスト（下記 Step 3）＋ `python -m pytest`

**Interfaces:**
- Consumes: Task 1–8 のすべて
- Produces: 公開済みマーケットプレイス `nomhiro/shiro-plugin-marketplace`。以降 CCA-F 講座の計画（`Udemy/CCA-F/docs/superpowers/plans/2026-09-13-cca-f-course.md`）がこのプラグインを前提に実行できる

- [ ] **Step 1: 全テストを通す**

Run: `python -m pytest -v`
Expected: PASS（合計 76 passed）

- [ ] **Step 2: プラグイン README を書く**

`plugins/udemy-exam-prep/README.md` に次を書く。

- 何をするプラグインか（1段落）
- ワークフロー全体図（Phase 0〜4 と R1〜R4 レビュー断面）
- スキル8個の一覧表（起動名 `/udemy-exam-prep:<name>`・目的）
- エージェント3個の一覧表
- `sections.md` front matter のスキーマ表（設計書 §5 のキー仕様をそのまま）
- 対応ベンダー6種と調査レシピの要約
- `scripts/` 5本の CLI 使用例
- 前提: Python 3.11+ / PyYAML / Playwright MCP（プラグイン同梱）

- [ ] **Step 3: ローカルスモークテスト**

`.mcp.json` と JSON の妥当性をコマンドで確認する。

Run:
```bash
python -m json.tool .claude-plugin/marketplace.json > /dev/null && echo "marketplace.json OK"
python -m json.tool plugins/udemy-exam-prep/.claude-plugin/plugin.json > /dev/null && echo "plugin.json OK"
python -m json.tool plugins/udemy-exam-prep/.mcp.json > /dev/null && echo ".mcp.json OK"
```
Expected: 3行すべて OK

スクリプトの CLI を一時ディレクトリで通す。

Run:
```bash
TMP=$(mktemp -d)
python plugins/udemy-exam-prep/scripts/init_course.py --dest "$TMP" \
  --cert SMOKE --cert-name "Smoke Test Cert" --vendor generic \
  --study-guide "https://example.com" --exam-minutes 90 --pass-score 700 \
  --mock-exams 2 --questions-per-exam 10
ls -1 "$TMP"
python plugins/udemy-exam-prep/scripts/profile.py "$TMP/sections.md"; echo "exit=$? (1 が正しい: domains 未確定)"
rm -rf "$TMP"
```
Expected: 6ファイルが created と表示される。`profile.py` は `domains` 未確定のため `FAIL` と exit 1（テンプレート段階では正しい挙動）

その後、Claude Code 上で次を実行して確認する（結果を記録する）。

```
/plugin marketplace add C:\Users\nom40\Documents\shiro-plugin-marketplace
/plugin install udemy-exam-prep@shiro-plugin-marketplace
```

確認項目:
1. スキル8個が一覧に現れる
2. `/udemy-exam-prep:` で補完される
3. **エージェント3個がどの名前で解決されるか**（設計書 §10 の未確定事項）。`doc-researcher` か `udemy-exam-prep:doc-researcher` かを実測し、結果に応じて `create-section` / `create-sections` の呼び出し名を修正する
4. playwright MCP がプラグイン経由で起動する

- [ ] **Step 4: 未確定事項の結果を設計書に反映**

Step 3 の項目3で判明したエージェント名前空間の規約を、`docs/superpowers/specs/2026-09-13-udemy-exam-prep-plugin-design.md` §10 に追記して「確定」に更新する。呼び出し名の修正が必要なら該当スキルを直す。

Run: `python -m pytest -v`
Expected: PASS（修正後も全件通る）

- [ ] **Step 5: Commit して GitHub に公開**

```bash
git add -A
git commit -m "docs: プラグイン README とスモークテスト結果を追加"
gh repo create nomhiro/shiro-plugin-marketplace --public --source=. --push \
  --description "nomhiro's Claude Code plugins"
gh repo view nomhiro/shiro-plugin-marketplace --json url,visibility
```
Expected: `"visibility": "PUBLIC"` と URL が表示される

公開後、マーケットプレイス参照を GitHub 側に切り替える。

```
/plugin marketplace remove shiro-plugin-marketplace
/plugin marketplace add nomhiro/shiro-plugin-marketplace
/plugin install udemy-exam-prep@shiro-plugin-marketplace
```

---

## 自己レビュー結果

**1. Spec coverage**

| 設計書の節 | 実装タスク |
|---|---|
| §4 リポジトリ・プラグイン構成 | Task 1 |
| §4 marketplace.json / plugin.json | Task 1 |
| §4 .mcp.json（フラットマップ） | Task 1（`test_plugin_mcp_json_is_flat_map`） |
| §4 スキル起動名の名前空間 | Task 7（`test_entrypoint_skills_document_the_namespaced_invocation`） |
| §5 front matter スキーマ | Task 2（+ Task 3 のテンプレート、Task 9 の README） |
| §5 検証ルール5項目 | Task 2（`test_*_is_reported` 5本） |
| §6 harness 汎用化（10ファイル） | Task 7（スキル8）＋ Task 8（エージェント3） |
| §6 ベンダー別調査レシピ表 | Task 7（`test_research_skill_lists_every_supported_vendor`） |
| §7 プレースホルダ8個 | Task 3（`test_placeholders_are_exactly_eight`） |
| §7 init-exam-course の動作 | Task 3（スクリプト）＋ Task 7（スキル） |
| §7 冪等性・上書きなし | Task 3（`test_init_course_is_idempotent_and_never_overwrites`） |
| §7 CLAUDE.md.tmpl の継承10項目 | Task 3 Step 3 |
| §8 ワークフローとレビュー断面 | Task 7（各スキル本文）＋ Task 9（README の全体図） |
| §9 エラー処理方針 | Task 2 / 3 / 4 / 6（各検証）＋ Task 7（未知 vendor の警告） |
| §9 スモークテスト8項目 | Task 9 Step 1・3 |
| §10 未確定事項（エージェント名前空間） | Task 9 Step 3 項目3・Step 4 |
| §12 公開手順 | Task 9 Step 5 |

**設計からの意図的な変更（1件）:** 設計書 §5 / §9 は検証 Python をスキル本文に埋め込む想定だったが、`scripts/` の実ファイル＋pytest に切り出した。理由は (1) テスト可能になる (2) 定義元が1箇所に確定する (3) テンプレート展開のようなファイル操作を LLM の手作業に任せず決定的にできる。設計書の意図（`quiz-csv-format` が検証の唯一の定義元）は、スキルがスクリプトを指す形で保たれている。これに伴い `.mcp.json` 以外に `scripts/` と `tests/` がリポジトリ構成に加わる。

**2. Placeholder scan:** 「TBD」「TODO」「後で実装」「適切なエラー処理を追加」はゼロ。Task 3 / 7 / 8 の Markdown 本文（テンプレートとスキル）は全文を掲載せず「移植元＋変更点リスト」の形にしているが、移植元のパスと変更内容を項目単位で具体的に指定しているため実行可能。

**3. Type consistency:**
- `scripts.validate_quiz_csv` の `HEADER` / `read_rows` / `write_rows` / `OPTION_PAIRS` / `correct_indices` を Task 5・6 が同名で使用 — 一致
- `scripts.profile` の `load_profile` / `validate_profile` / `domain_quota` / `domain_names` を Task 3・6 が同名で使用 — 一致
- `scripts.init_course` の `PLACEHOLDERS` / `render` / `init_course` / `InitError` — Task 3 内で一致
- `scripts.validate_exam` の `BANK_FIELDS` 7項目が `question-bank.md.tmpl` の表ヘッダー（section / q# / domain / task_statement / tested_concept / scenario / 問題文冒頭60字）と同数・同順 — 一致
- pytest の合計件数: Task 1 の 4 + Task 2 の 11 + Task 3 の 9 + Task 4 の 15 + Task 5 の 10 + Task 6 の 13 = 62（Task 6 Step 5）、+ Task 7 の 7 + Task 8 の 7 = 76（Task 9 Step 1）— 一致
