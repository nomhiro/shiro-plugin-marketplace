# udemy-exam-prep

認定資格の試験対策問題集（Udemy 演習テスト講座）を作るハーネス。公式ドキュメントの調査から、本番相当フル模試の生成・検証、Udemy へのアップロードまでを、スキル8個・サブエージェント3個・検証スクリプト6本で自動化します。

資格固有の情報は **プロジェクト側 `sections.md` の YAML front matter だけ** が持ちます。ハーネス自体は資格非依存なので、同じプラグインを任意のベンダー・任意の資格に使えます。

## 導入

```
/plugin marketplace add nomhiro/shiro-plugin-marketplace
/plugin install udemy-exam-prep@shiro-plugin-marketplace
```

前提: Python 3.11+ / PyYAML。Playwright MCP はプラグインが同梱しています。

## ワークフロー

```
Phase 0    /udemy-exam-prep:init-exam-course <CERT>
             → CLAUDE.md / sections.md / question-bank.md / removed-questions.md
               / .gitignore / Udemy CSV 参考ファイル を展開（既存ファイルは上書きしない）
             ↓
Phase 0.5  /udemy-exam-prep:create-sections <CERT>
             → 学習ガイドからブループリントを起草し front matter の domains を確定
             ★ R1: ドメイン・配分・網羅性・front matter 検証5項目 ★
             ↓
Phase 1a   doc-researcher を技術領域ごとに並列起動（1回限り）
             → research/*.md に共有 digest（事実リスト＋出典URL）
             ↓
Phase 1b   /udemy-exam-prep:create-section N   （1 〜 mock_exams を順に）
             → question-author でサンプル生成
             ★ R2: 解説スタイル・難易度・distractor の質（初回のみ）★
             → 残りを生成 → exam-validator で配分/シラバス外/重複検証
             → 出典URL正規化 → 選択肢シャッフル（最良シード自動走査）
             ★ R3: セクション全体レビュー ★
             ↓
Phase 2    /udemy-exam-prep:create-udemy-course
             → Udemy にコース作成・基本設定・学習目的・メッセージ
             ↓
Phase 3    /udemy-exam-prep:upload-practice-tests
             → CSV 事前検証 → 演習テスト追加・設定・CSV 一括アップロード
             ★ R4: CSV 検証 FAIL 時のみ ★
             ↓
Phase 4    価格設定・審査提出・公開 — すべて人が行う（自動化対象外）
```

## スキル

| スキル | 起動 | 目的 |
|---|---|---|
| `init-exam-course` | `/udemy-exam-prep:init-exam-course CCA-F` | テンプレートを展開して新規プロジェクトを初期化。冪等で既存ファイルを上書きしない |
| `create-sections` | `/udemy-exam-prep:create-sections CCA-F` | 学習ガイドからブループリントを起草し front matter を確定。**R1 で停止** |
| `create-section` | `/udemy-exam-prep:create-section 2` | フル模試1本を生成・検証・シャッフル。**R2（初回）/ R3 で停止** |
| `create-udemy-course` | `/udemy-exam-prep:create-udemy-course` | Udemy にコース作成と基本設定 |
| `upload-practice-tests` | `/udemy-exam-prep:upload-practice-tests` | 各セクションの quiz.csv をアップロード。**R4（FAIL時のみ）** |
| `quiz-csv-format` | 自動発火 | Udemy 17カラム CSV の規約（定義元） |
| `research-cert-docs` | 自動発火 | ベンダー別の調査レシピと sources.md フォーマット（定義元） |
| `udemy-bulk-upload` | 自動発火 | Playwright での Udemy 操作レシピ（定義元） |

## サブエージェント

| エージェント | 役割 |
|---|---|
| `doc-researcher` | 1つの技術領域を公式ドキュメントで調査し digest（事実リスト＋出典URL＋アンチパターン）を返す。領域数だけ並列起動する |
| `question-author` | digest を入力に quiz.csv の問題行を生成する。`quiz.csv` のみを書き、`question-bank.md` は触らない |
| `exam-validator` | CSV整合性・ドメイン配分・タイプ比率・シラバス外・本横断重複を検証し、退避と `question-bank.md` 更新を行う |

## 試験プロファイル（`sections.md` front matter）

ハーネスの唯一の入力インターフェースです。

```yaml
---
cert: CCA-F                                 # 必須。試験番号
cert_name: Claude Certified Architect - Foundations   # 必須。正式名称
cert_name_ja: ...                           # 任意。日本語名称
exam_code: CCAR-F                           # 任意。公式の試験コード
vendor: anthropic                           # 必須。anthropic/microsoft/github/cloudflare/ipa/generic
credential_url: https://...                 # 任意
study_guide: https://...                    # 必須。ブループリント抽出元
mode: mock-exam                             # 必須。現状 mock-exam のみ
exam:
  minutes: 120                              # 必須。Udemy の制限時間になる
  pass_score: 720                           # 必須
  max_score: 1000                           # 任意（既定 1000）
  language: en                              # 必須。問題文の言語
mock_exams: 6                               # 必須。1〜6（Udemy の演習テスト上限が6）
questions_per_exam: 60                      # 必須。実試験の問題数に合わせるのが望ましい
max_per_concept: 3                          # 任意（既定 2）。同一概念の再出題上限
question_types:                             # 必須
  multiple-choice: "75%"
  multi-select: "25%"
scenario_ratio_min: "100%"                  # 任意
primary_sources:                            # 必須。priority 昇順に使う
  - priority: 1
    tool: local-file
    scope: research/CCA-F-Exam-Guide.txt
domains:                                    # 必須。create-sections が確定させる
  - id: D1
    name: Agentic Architecture & Orchestration   # quiz.csv の Domain 列にこの値がそのまま入る
    ratio: "27%"
    per_exam: 16
---
```

### 検証ルール

処理開始前に次を検証し、違反時は**推測で続行せず明示エラーで停止**します。

1. 必須キーの存在
2. `sum(domains[].per_exam) == questions_per_exam`
3. `domains[].id` の一意性
4. `mode == "mock-exam"`
5. `mock_exams >= 1` かつ `questions_per_exam >= 1`

## 対応ベンダーと調査レシピ

| vendor | 優先1 | 優先2 | 優先3 |
|---|---|---|---|
| `anthropic` | 公式 Exam Guide PDF（ローカル保存） | `docs.claude.com` を WebFetch | `modelcontextprotocol.io` |
| `microsoft` | `microsoft_docs_search` / `_fetch`（MCP） | context7 `query-docs` | WebFetch（Learn 検索） |
| `github` | WebFetch（`docs.github.com`） | context7 `query-docs` | WebSearch |
| `cloudflare` | `search_cloudflare_documentation`（MCP） | WebFetch（`developers.cloudflare.com`） | context7 |
| `ipa` | WebFetch（`www.ipa.go.jp` の PDF） | WebSearch | — |
| `generic` | WebSearch で公式ドメイン特定 → WebFetch | context7 | — |

未知の `vendor` は `generic` にフォールバックし警告を出します。二次情報（個人ブログ・受験記）は**難易度の校正にのみ使い、出典には使いません**。

## 検証スクリプト

すべて標準ライブラリ + PyYAML のみ。`${CLAUDE_PLUGIN_ROOT}/scripts/` にあります。

```bash
# 試験プロファイルの検証
python scripts/profile.py sections.md

# 新規プロジェクトの初期化（冪等・上書きなし）
python scripts/init_course.py --dest . --cert CCA-F \
  --cert-name "Claude Certified Architect - Foundations" --vendor anthropic \
  --study-guide "https://..." --exam-minutes 120 --pass-score 720 \
  --mock-exams 6 --questions-per-exam 60

# 17カラム CSV の検証（BOM/正解数/範囲/distractor/ペア/必須列）
python scripts/validate_quiz_csv.py section0*/quiz.csv

# 出典 URL のロケール正規化（冪等）
python scripts/normalize_urls.py section0*/quiz.csv

# 選択肢シャッフル（原本退避 + 最良シード自動走査 + 位置分布検証）
python scripts/shuffle_options.py section01-mock-exam-1/quiz.csv

# ドメイン配分・シラバス整合・本横断重複の検証
python scripts/validate_exam.py --sections sections.md \
  --bank question-bank.md section0*/quiz.csv
```

CSV の読み書きは `scripts/validate_quiz_csv.py` の `read_rows` / `write_rows` を使います（`utf-8` / BOM 無し / `newline=''` / `QUOTE_MINIMAL` が保証されます）。

## 設計上の判断

**payload と harness の分離。** 問題本文・ブループリント・プロジェクト方針は講座リポジトリ（payload）に、ワークフロー実装はこのプラグイン（harness）に置きます。プラグインを更新すれば全講座が同じ世代のハーネスを使います。

**判定ロジックをスクリプトに置く。** ドメイン配分・CSV 規約・重複・位置分布の判定は Python に実装して pytest で担保しています。エージェントの出力揺れに関係なく同じ基準が適用されます。スキルとエージェントはスクリプトを呼ぶだけで、検証ロジックを再実装しません。

**シャッフルは最良シード自動走査。** 単一固定シードは当たり外れが大きく、実績として seed=42 が正解を1位置に 78.8% 偏らせました。原本 `quiz.raw.csv` を一度だけ退避して常に原本からシャッフルし（再シャッフルの罠の防止）、シードを走査して正解位置が最も均等になるものを採用します。

**期待票数は「その位置を提供した問題」からのみ積む。** 4択中心に5/6択が混在しても、位置5・6が誤検知になりません。

## 既知の制約

- Udemy の演習テスト専用コースは**最大6テスト**。`mock_exams` は6以下にする
- コースが**有料設定済み**でないと演習テストを追加できない
- Udemy API は公開済みテストの個別問題を編集できない。入れ替えはテスト削除→再作成（`udemy-bulk-upload` にワークアラウンドあり）
- Udemy は CSV に BOM があるとヘッダー不正と判定する
- セクション構成は `mock-exam` のみ対応（トピック別構成は未対応）

## ライセンス

MIT
