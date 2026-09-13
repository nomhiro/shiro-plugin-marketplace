# udemy-exam-prep プラグイン / shiro-plugin-marketplace 設計書

> 作成日: 2026-09-13
> ステータス: 承認済み（実装計画待ち）
> 対象: `C:\Users\nom40\Documents\shiro-plugin-marketplace`

## 1. 背景と目的

Udemy の試験対策演習テスト講座は現在、試験ごとのプロジェクトディレクトリ（`Udemy/AI-103`、`Udemy/AB-730` 等）に `.claude/skills` と `.claude/agents` を都度コピーして運用している。最新世代は **AI-103**（フル模試6本・計300問）で、その `CLAUDE.md` には既に次の分離が明記されている。

- **payload（資格固有）:** `CLAUDE.md` / `sections.md` / `question-bank.md` / `section0N-*/` / `removed-questions.md` / `research/`
- **harness（資格非依存）:** `.claude/skills/` / `.claude/agents/`

本設計の目的は2つ。

1. harness を **Claude Code プラグイン `udemy-exam-prep`** として切り出し、`nomhiro/shiro-plugin-marketplace` で配布・バージョン管理する
2. payload を **講座テンプレート**として同プラグインに同梱し、初期化スキルで新規講座を即座に立ち上げられるようにする

### 解決する問題

| 現状の問題 | 本設計での解決 |
|---|---|
| 新講座ごとに `.claude/` を手動コピー。コピー元の世代がばらつく（GH-600 は旧世代の `create-quiz` / `quiz-shuffle` 構成のまま） | プラグイン更新で全講座が同一世代の harness を参照 |
| harness に `AI-103` がハードコードされており他資格へそのまま使えない | front matter 駆動で任意ベンダー・任意資格に対応 |
| `CLAUDE.md` 等の payload 雛形が存在せず、毎回既存講座からコピー＆書き換え | `init-exam-course` がプレースホルダ置換つきで展開 |

## 2. 決定事項サマリ

| 論点 | 決定 | 理由 |
|---|---|---|
| リポジトリ公開範囲 | **Public** | harness に問題本文（payload）を含まないため機密性の問題がない。`/plugin marketplace add nomhiro/shiro-plugin-marketplace` だけで追加でき、他マシンへの展開も容易 |
| プラグイン粒度 | **単一プラグイン `udemy-exam-prep`** | `create-section` → `question-author` → `quiz-csv-format` の依存が密結合で、分割の実利が薄い |
| テンプレート配置 | **プラグイン内 `templates/exam-course/` + `init-exam-course` スキル** | プラグイン更新でテンプレートも自動追従。手動コピーとプレースホルダ手置換が不要 |
| 対応資格スコープ | **汎用（任意ベンダー）** | 情報源をプロジェクト側 front matter で宣言。Anthropic / Microsoft / GitHub / Cloudflare / IPA / generic のレシピをプラグインが保持 |
| セクション構成モード | **mock-exam のみ** | AI-103 で確立した最新世代に絞る。ドメイン配分ノルマ・`question-bank` 重複管理が全てこのモード前提 |
| 試験プロファイルの宣言場所 | **`sections.md` の front matter** | 既にメタデータ行（`> mode:` `> Source of Truth:` `> 試験概要:`）を持ち、スキルが読んでいるファイル。新規ファイルを増やさない |
| AI-103 の既存 `.claude/` | **併存（削除しない）** | プロジェクトローカルがプラグインより優先されるため挙動不変。新規講座で実動作を検証してから削除を判断 |

## 3. 現状資産の棚卸し

### harness（移植対象）

| ファイル | 行数 | 役割 | `AI-103` 出現数 |
|---|---|---|---|
| `skills/create-sections/SKILL.md` | 269 | Phase 0 オーケストレータ（ブループリント起草・R1） | 6 |
| `skills/create-section/SKILL.md` | 426 | Phase 1 オーケストレータ（模試1本生成・R2/R3） | 1 |
| `skills/create-udemy-course/SKILL.md` | 256 | Phase 2 オーケストレータ（コース作成） | 3 |
| `skills/upload-practice-tests/SKILL.md` | 163 | Phase 3 オーケストレータ（アップロード・R4） | 0 |
| `skills/quiz-csv-format/SKILL.md` | 138 | 再利用ナレッジ（17カラム規約・検証Python） | 1 |
| `skills/research-cert-docs/SKILL.md` | 121 | 再利用ナレッジ（調査レシピ・source優先表） | 3 |
| `skills/udemy-bulk-upload/SKILL.md` | 136 | 再利用ナレッジ（Playwright 操作） | 0 |
| `agents/doc-researcher.md` | 126 | サブトピック調査（隔離コンテキスト） | 3 |
| `agents/question-author.md` | 253 | 問題起草 | 5 |
| `agents/exam-validator.md` | 91 | 配分・シラバス外・重複検証 | 1 |
| **計** | **1,979** | | **23** |

### payload（テンプレート化対象）

`CLAUDE.md` / `sections.md` / `question-bank.md` / `removed-questions.md` / `.gitignore` / `PracticeTestBulkQuestionUploadTemplate_v2.csv`

### テンプレート化しないもの

| ファイル | 理由 |
|---|---|
| `udemy-course-meta.md` | `create-udemy-course` が起草する成果物。雛形を置くと Udemy 項目仕様の定義元が2箇所に分散する |
| `research/` `section0N-*/` | 各スキルが生成する。空ディレクトリを先に作る意味がない |
| `courseImage.*` | 講座ごとの固有成果物 |
| `.claude/settings.local.json` | マシン固有の権限設定。`.gitignore` 対象 |

## 4. リポジトリ・プラグイン構成

```
shiro-plugin-marketplace/
├── .claude-plugin/
│   └── marketplace.json
├── plugins/
│   └── udemy-exam-prep/
│       ├── .claude-plugin/
│       │   └── plugin.json
│       ├── .mcp.json
│       ├── skills/
│       │   ├── init-exam-course/SKILL.md        # 新規
│       │   ├── create-sections/SKILL.md
│       │   ├── create-section/SKILL.md
│       │   ├── create-udemy-course/SKILL.md
│       │   ├── upload-practice-tests/SKILL.md
│       │   ├── quiz-csv-format/SKILL.md
│       │   ├── research-cert-docs/SKILL.md
│       │   └── udemy-bulk-upload/SKILL.md
│       ├── agents/
│       │   ├── doc-researcher.md
│       │   ├── question-author.md
│       │   └── exam-validator.md
│       ├── templates/
│       │   └── exam-course/
│       │       ├── CLAUDE.md.tmpl
│       │       ├── sections.md.tmpl
│       │       ├── question-bank.md.tmpl
│       │       ├── removed-questions.md.tmpl
│       │       ├── gitignore.tmpl
│       │       └── PracticeTestBulkQuestionUploadTemplate_v2.csv
│       └── README.md
├── docs/superpowers/specs/
│   └── 2026-09-13-udemy-exam-prep-plugin-design.md
├── README.md
├── LICENSE                                        # MIT
└── .gitignore
```

ライセンスは **MIT** とする（公開リポジトリ。参考にした公式プラグイン群および `tsumiki` も MIT）。

### marketplace.json

公式リポジトリ（`anthropics/claude-plugins-official`）と同形式。リポジトリ内プラグインは相対パス `source` で参照する。

```json
{
  "$schema": "https://code.claude.com/schemas/marketplace.json",
  "name": "shiro-plugin-marketplace",
  "owner": { "name": "nomhiro", "url": "https://github.com/nomhiro" },
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
      "keywords": ["udemy", "certification", "practice-test", "quiz"]
    }
  ]
}
```

### .mcp.json（プラグイン同梱 MCP）

公式 `playwright` プラグインの実装に合わせ、**`mcpServers` ラッパーを持たないフラットマップ**で定義する（プロジェクト直下の `.mcp.json` とは形式が異なる点に注意）。

```json
{ "playwright": { "command": "npx", "args": ["@playwright/mcp@latest"] } }
```

これによりテンプレート側に `.mcp.json` を置く必要がなくなる。

### スキル起動名の変更

プラグイン化に伴い起動名が名前空間付きになる。

| 現在（プロジェクトローカル） | プラグイン経由 |
|---|---|
| `/create-sections AI-103` | `/udemy-exam-prep:create-sections AI-103` |
| `/create-section 2` | `/udemy-exam-prep:create-section 2` |

テンプレート `CLAUDE.md.tmpl` の起動例はすべて後者に書き換える。自然言語からの自動発火は `description` 経由で従来どおり機能する。

## 5. 試験プロファイル（front matter）スキーマ

`sections.md` 冒頭の YAML front matter を harness の唯一の入力インターフェースとする。

```yaml
---
cert: AI-103
cert_name: Azure AI apps and agents developer associate
cert_name_ja: Azure での AI アプリとエージェントの開発
vendor: microsoft
credential_url: https://learn.microsoft.com/ja-jp/credentials/certifications/agentic-ai-developer/
study_guide: https://learn.microsoft.com/ja-jp/credentials/certifications/resources/study-guides/ai-103
mode: mock-exam
exam:
  minutes: 120
  pass_score: 700
  max_score: 1000
  language: ja
mock_exams: 6
questions_per_exam: 50
question_types:
  multiple-choice: "60-70%"
  multi-select: "30-40%"
scenario_ratio_min: "30%"
primary_sources:
  - priority: 1
    tool: microsoft_docs_search
    scope: Microsoft Learn 全般
  - priority: 2
    tool: query-docs
    scope: 関連 SDK
  - priority: 3
    tool: WebFetch
    scope: MCP 未対応ページ・リリースノート
domains:
  - id: D1
    name: Azure AI ソリューションの計画と管理
    ratio: "25-30%"
    per_exam: 14
  - id: D2
    name: 生成 AI とエージェント ソリューションの実装
    ratio: "30-35%"
    per_exam: 16
---
```

### キー仕様

| キー | 必須 | 型 | 用途 | 読み取るコンポーネント |
|---|---|---|---|---|
| `cert` | ✓ | string | 試験番号。ディレクトリ名・コースタイトルに使用 | 全スキル |
| `cert_name` | ✓ | string | 正式名称（原語） | `create-udemy-course` |
| `cert_name_ja` | | string | 日本語名称。無い場合は `cert_name` を使う | `create-udemy-course` |
| `vendor` | ✓ | enum | `anthropic` / `microsoft` / `github` / `cloudflare` / `ipa` / `generic` | `research-cert-docs` / `doc-researcher` |
| `credential_url` | | url | 認定資格ページ | `create-udemy-course` |
| `study_guide` | ✓ | url | 学習ガイド。ブループリント抽出元 | `create-sections` |
| `mode` | ✓ | enum | 現状 `mock-exam` のみ。他値はエラー | `create-section` / `exam-validator` |
| `exam.minutes` | ✓ | int | 試験時間。Udemy のテスト制限時間に反映 | `upload-practice-tests` |
| `exam.pass_score` | ✓ | int | 合格スコア | `create-udemy-course` |
| `exam.max_score` | | int | 満点（既定 1000） | `create-udemy-course` |
| `exam.language` | ✓ | string | 出題言語（既定 `ja`） | `question-author` |
| `mock_exams` | ✓ | int ≥1 | フル模試の本数 | `create-section` / `exam-validator` |
| `questions_per_exam` | ✓ | int ≥1 | 1本あたり問題数 | `create-section` / `question-author` |
| `question_types` | ✓ | map | 出題形式の比率 | `question-author` |
| `scenario_ratio_min` | | string | シナリオ問題の下限比率（既定 `30%`） | `question-author` |
| `primary_sources` | ✓ | list | 一次情報源の優先表。`priority` 昇順で使う | `doc-researcher` |
| `domains` | ✓ | list | ドメイン定義。`id` は一意。ドメイン数は可変（AI-103 の D1〜D5 固定を撤廃） | `create-section` / `exam-validator` / `question-author` |

### 検証ルール

front matter を読むコンポーネントは、処理開始前に次を検証し、違反時は**推測で続行せず明示エラーで停止**する。

1. 必須キーの存在
2. `sum(domains[].per_exam) == questions_per_exam`
3. `domains[].id` の一意性
4. `mode == "mock-exam"`（他値は未対応として停止）
5. `mock_exams >= 1` かつ `questions_per_exam >= 1`

検証は `create-section` の冒頭と `exam-validator` の冒頭で実施する。実装は `quiz-csv-format` と同様に Python スニペットをスキル内に埋め込む。

## 6. harness の汎用化

| ファイル | 変更内容 |
|---|---|
| `create-sections` | 引数を `<試験番号> [学習ガイドURL]` に一般化。学習ガイド取得前に**front matter を起草**し、R1 レビューで front matter とブループリントを同時に承認させる。`AI-103` 固有記述6箇所を除去 |
| `research-cert-docs` | 「ステップ1: 資格の種類を判定」を front matter の `vendor` 参照に置換。ベンダー別レシピ表（次節）をこのスキルが唯一の定義元として保持。`sources.md` フォーマット定義は無変更 |
| `doc-researcher` | 情報源の選択を `primary_sources` の `priority` 昇順に従う形へ。ベンダー固有の MCP ツール名は `research-cert-docs` を参照し再掲しない |
| `question-author` | AI-103 語彙リスト（Foundry / RAG / grounding 等）を削除し、プロジェクト `CLAUDE.md`「用語表記ルール」を参照する形へ。ノルマ・比率は front matter から受け取る |
| `exam-validator` | D1〜D5 固定を撤廃し `domains` を動的に読む。重複検証の `question-bank.md` 突き合わせロジックは無変更 |
| `create-section` | `questions_per_exam` / `domains` / `mock_exams` を front matter から読む。選択肢シャッフル（`random.seed(42)` 決定的）と正解位置分布検証は無変更 |
| `quiz-csv-format` | AI-103 固有の例示を汎用例に差し替え。17カラム規約・BOM 規約・検証 Python は無変更 |
| `udemy-bulk-upload` | 無変更（ハードコードなし） |
| `upload-practice-tests` | テスト制限時間を `exam.minutes` の値そのまま（本番と同条件。問題数に応じた按分はしない）、合格ラインを従来どおり 70%、質問のランダム化を ON に設定。ハードコードなし |

### ベンダー別調査レシピ表（`research-cert-docs` が保持）

| vendor | 優先1 | 優先2 | 優先3 |
|---|---|---|---|
| `microsoft` | `microsoft_docs_search` / `microsoft_docs_fetch`（MCP） | context7 `query-docs`（関連 SDK） | WebFetch（`learn.microsoft.com/search/?terms=`） |
| `github` | WebFetch（`docs.github.com`） | context7 `query-docs` | WebSearch |
| `cloudflare` | `search_cloudflare_documentation`（MCP） | WebFetch（`developers.cloudflare.com`） | context7 `query-docs` |
| `ipa` | WebFetch（`www.ipa.go.jp` のシラバス・過去問 PDF） | WebSearch | — |
| `generic` | WebSearch で公式ドメインを特定 → WebFetch | context7 `query-docs` | — |

未知ベンダーが `vendor: generic` で来た場合もこの表の generic 行で動作する。新ベンダー専用レシピが必要になった時点で行を追加する（プラグイン更新で全講座に反映）。

MCP ツール名は環境によって `plugin_` プレフィックスが付くため、スキル本文では機能名（`microsoft_docs_search` 等）で言及する方針を維持する。

## 7. テンプレートと `init-exam-course`

### プレースホルダ（8個）

| プレースホルダ | 例 | ヒアリングで取得 |
|---|---|---|
| `{{CERT_ID}}` | `CCA-F` | ✓（引数でも受け取る） |
| `{{CERT_NAME}}` | `Cloudflare Certified Associate - Fundamentals` | ✓ |
| `{{VENDOR}}` | `cloudflare` | ✓（選択式） |
| `{{STUDY_GUIDE_URL}}` | `https://...` | ✓ |
| `{{EXAM_MINUTES}}` | `90` | ✓ |
| `{{PASS_SCORE}}` | `700` | ✓ |
| `{{MOCK_EXAMS}}` | `6` | ✓（既定 6） |
| `{{QUESTIONS_PER_EXAM}}` | `50` | ✓（既定 50） |

ドメイン表は学習ガイドを取得しないと埋まらないため、`init-exam-course` では埋めない。`sections.md.tmpl` の `domains:` と `## 試験ブループリント` は TODO マーカーを置き、`/create-sections` が確定させる。

### `init-exam-course` の動作

```
/udemy-exam-prep:init-exam-course CCA-F
  1. 引数から {{CERT_ID}} を取得（未指定ならヒアリング）
  2. 残り7項目をヒアリング（既定値つき）
  3. templates/exam-course/ を展開しプレースホルダ置換
       CLAUDE.md / sections.md / question-bank.md / removed-questions.md
       .gitignore（gitignore.tmpl からリネーム）
       PracticeTestBulkQuestionUploadTemplate_v2.csv（置換なしコピー）
  4. 生成・スキップしたファイルを一覧表示
  5. 次アクション /udemy-exam-prep:create-sections {{CERT_ID}} を提示
```

### 冪等性と安全性

- **既存ファイルは上書きしない。** 存在するものは skip して報告する。空でないディレクトリでも安全に再実行でき、テンプレート追加後の差分適用にも使える
- 上書きが必要な場合はユーザーに明示的に指示させる（`--force` は初版では実装しない）
- `gitignore.tmpl` という名前で同梱する理由: `.gitignore` のままだとマーケットプレイスリポジトリ自身の Git 管理対象から外れる

### `CLAUDE.md.tmpl` に継承する内容

AI-103 の `CLAUDE.md` から次を雛形化して引き継ぐ。

- プロジェクト概要（試験番号・正式名称・合格スコア・言語・資格 URL・学習ガイド）
- 構造方針（mock-exam・ドメイン横断・パラレルフォーム）
- 一次情報源の優先表
- ディレクトリ構成図
- ワークフロー全体図（Phase 0〜4）
- エントリーポイント表（名前空間付き起動名）
- レビュー断面 R1〜R4 の役割表
- クイズ作成ガイドライン9項目（用語表記ルールを含む）
- 継続性の設計（試験更新時の手順）・Source of Truth 一覧
- 技術的注意事項（日本語 CSV は Python で書く / BOM 無し / MCP 名は環境依存 / Playwright はアクセシビリティツリー駆動）

`payload` / `harness` の分離を説明していた「ハーネス設計の意図」節は、harness がプラグインへ移動したことを説明する内容に更新する。

## 8. ワークフローとレビュー断面

```
/init-exam-course CCA-F
   → CLAUDE.md / sections.md(front matter) / question-bank.md
     removed-questions.md / .gitignore / 参考CSV
        ↓
/create-sections CCA-F
   → 学習ガイド取得 → ドメイン×サブトピック抽出 → 配分算出
   → ★R1: front matter + ブループリント レビュー★ → sections.md 確定
        ↓
Phase 1a（/create-section 1 の内部・初回のみ）
   → doc-researcher 並列起動 → research/D{n}-{subtopic}.md
        ↓
/create-section 1 .. N
   → question-author（ノルマ + question-bank 渡し）
   → ★R2: サンプルレビュー（初回のみ）★
   → question-author 残り生成 → exam-validator
   → 選択肢シャッフル（random.seed(42)）→ 正解位置分布検証
   → ★R3: セクション全体レビュー★ → quiz.csv / sources.md
        ↓
/create-udemy-course
   → udemy-course-meta.md 起草 → Playwright でコース作成・基本設定
        ↓
/upload-practice-tests
   → CSV 事前検証 → ★R4: FAIL 時のみレビュー★ → アップロード
        ↓
Phase 4: 審査提出・公開（手動・自動化対象外）
```

レビュー断面 R1〜R4 の役割は AI-103 の設計をそのまま維持する。R1 の確認対象に **front matter の検証ルール5項目**を追加する。

## 9. 検証・エラー処理

### エラー処理方針

| 事象 | 挙動 |
|---|---|
| front matter のパース失敗・必須キー欠落 | 明示エラーで停止。推測で続行しない |
| `sum(per_exam) != questions_per_exam` | エラーで停止し差分を報告 |
| `mode` が `mock-exam` 以外 | 未対応として停止 |
| `init-exam-course` で生成先にファイルが既存 | skip して報告（上書きしない） |
| `vendor` が未知の値 | `generic` レシピにフォールバックし、その旨を警告表示 |
| CSV 検証 FAIL | R4 レビューで修正方針を確認してから自動修正 |

### スモークテスト（push 前にローカルで実施）

1. `/plugin marketplace add C:\Users\nom40\Documents\shiro-plugin-marketplace`（ローカルパスで追加）
2. `/plugin install udemy-exam-prep@shiro-plugin-marketplace`
3. スキル8個が一覧に現れ、`/udemy-exam-prep:` で補完されること
4. 空の `Udemy/CCA-F` で `init-exam-course` を実行し、生成物6点とプレースホルダ置換を確認
5. 同じディレクトリで再実行し、全ファイルが skip 報告されること（冪等性）
6. エージェント3個がプラグイン経由で解決できること（**未確定事項** — 次節）
7. playwright MCP がプラグイン経由で起動すること
8. `marketplace.json` / `plugin.json` が `python -m json.tool` を通ること

AI-103 での回帰テストは実施しない。プロジェクトローカルの `.claude/` がプラグインより優先されるため挙動は変わらない。

## 10. 未確定事項

| 項目 | 内容 | 状態 |
|---|---|---|
| プラグイン同梱エージェントの名前空間 | `agents/` に置いたサブエージェントが `doc-researcher` で解決されるか `udemy-exam-prep:doc-researcher` になるか | **未確定。** スクリプトとスキルは実測なしで確定できたが、エージェント名の解決はプラグインを実インストールしないと確認できない。公式マーケットプレイスには `agents/` を持つプラグインが8個あるため機構自体は存在する。`create-section` / `create-sections` はエージェントを名前で呼ぶが、Claude Code は同名エージェントを解決できる想定で書いてある。解決に失敗した場合は呼び出し名に `udemy-exam-prep:` を付ける1行修正で済む |
| スクリプトの直接実行 | `python .../scripts/x.py` で兄弟モジュールが解決できるか | **確定・修正済み。** 当初 `ModuleNotFoundError` で全滅していた（pytest では `pythonpath` 設定のため通っていた）。各スクリプトに `__package__` 判定の sys.path ブートストラップを追加し、CLI をサブプロセスで叩く `tests/test_cli.py`（8本）で回帰を防いでいる |

## 11. スコープ外

- AI-103 の `.claude/skills` `.claude/agents` 削除（併存のまま。新規講座での実動作検証後に別タスクで判断）
- `topic-section` モード（AI-300 / AB-730 / AB-731 形式のトピック別セクション構成）
- AZ-700 系の動画講座ハーネス（`make-lecture-slides` / `make-lecture-movie` 等）
- 旧世代プロジェクト（GH-100 / GH-200 / GH-600 / AB-900 等）のプラグイン移行
- `Udemy/tool/udemy-create-pracexam-by-ai`（Azure OpenAI ベースの Python ツール）の統合
- コース画像生成の自動化
- `init-exam-course --force`（上書きモード）

## 12. 公開手順

```bash
cd C:/Users/nom40/Documents/shiro-plugin-marketplace
git add -A && git commit -m "udemy-exam-prep プラグイン初版と講座テンプレート"
gh repo create nomhiro/shiro-plugin-marketplace --public --source=. --push
```

公開後、ローカルパスで追加したマーケットプレイスを GitHub 参照に切り替える。

```
/plugin marketplace remove shiro-plugin-marketplace
/plugin marketplace add nomhiro/shiro-plugin-marketplace
/plugin install udemy-exam-prep@shiro-plugin-marketplace
```

## 13. 参照

- AI-103 プロジェクト: `C:\Users\nom40\Documents\Udemy\AI-103`（`nomhiro/udemy-ai-103`）
- 公式マーケットプレイス形式の参考: `anthropics/claude-plugins-official`、`cloudflare/skills`、`classmethod/tsumiki`
- プラグイン同梱 MCP の形式参考: 公式 `playwright` プラグインの `.mcp.json`
