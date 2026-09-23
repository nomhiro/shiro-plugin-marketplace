# udemy-exam-prep

認定資格の試験対策問題集（Udemy 演習テスト講座）を作るハーネス。公式ドキュメントの調査から、本番相当フル模試の生成・検証、Udemy へのアップロードまでを、スキル10個・サブエージェント3個・検証スクリプト群で自動化します。

資格固有の情報は **プロジェクト側 `sections.md` の YAML front matter だけ** が持ちます。ハーネス自体は資格非依存なので、同じプラグインを任意のベンダー・任意の資格に使えます。

## 導入

```
/plugin marketplace add nomhiro/shiro-plugin-marketplace
/plugin install udemy-exam-prep@shiro-plugin-marketplace
```

前提: Python 3.11+ / PyYAML。Udemy の操作は Claude in Chrome（ログイン済みの Chrome をそのまま使う）を第一手段とし、使えない環境では Playwright MCP（プラグイン同梱）を代替にします。

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
             → 長さバイアス検出 → 出典URL正規化 → 選択肢シャッフル（最良シード自動走査）
             ★ R3: セクション全体レビュー ★
             ↓
Phase 1c   /udemy-exam-prep:review-section <N|all>   （任意・強く推奨）
             → 全問・全カラムを1問ずつ精読（製品名の和訳・翻訳調・表記ゆれ・出典と正答の食い違い）
             → 統一表記シートで一括修正 → check_invariants.py で不変条件を検査
             ↓
Phase 2    /udemy-exam-prep:create-udemy-course
             → Udemy にコース作成・基本設定・学習目的・メッセージ
             ↓
Phase 3    /udemy-exam-prep:upload-practice-tests
             → CSV 事前検証 → 演習テスト追加・設定・CSV 一括アップロード
             ★ R4: CSV 検証 FAIL 時のみ ★
             ↓
Phase 4    価格設定・審査提出・公開 — プロジェクトの CLAUDE.md の公開方針に従う
             （記載がなければ人が行う。ユーザー承認のうえで自動化対象に変えられる）
             ↓
Phase 5    /udemy-exam-prep:handle-student-feedback
             → 公開後に受講者の指摘が来たとき。一次情報で検証 → 講座全体を見直し
               → CSV 修正 → Udemy の編集画面で書き換え → 公開 → Q&A へ返信
             ★ 公開と返信はユーザーの許可を得てから ★
```

## スキル

| スキル | 起動 | 目的 |
|---|---|---|
| `init-exam-course` | `/udemy-exam-prep:init-exam-course CCA-F` | テンプレートを展開して新規プロジェクトを初期化。冪等で既存ファイルを上書きしない |
| `create-sections` | `/udemy-exam-prep:create-sections CCA-F` | 学習ガイドからブループリントを起草し front matter を確定。**R1 で停止** |
| `create-section` | `/udemy-exam-prep:create-section 2` | フル模試1本を生成・検証・シャッフル。**R2（初回）/ R3 で停止** |
| `create-udemy-course` | `/udemy-exam-prep:create-udemy-course` | Udemy にコース作成と基本設定 |
| `upload-practice-tests` | `/udemy-exam-prep:upload-practice-tests` | 各セクションの quiz.csv をアップロード。**R4（FAIL時のみ）** |
| `review-section` | `/udemy-exam-prep:review-section 2` | 完成した quiz.csv の精読レビューと一括修正。修正前後の不変条件（正解・配分・選択肢数・出典・正誤印）をスクリプトで検査 |
| `handle-student-feedback` | `/udemy-exam-prep:handle-student-feedback` | 受講者の指摘への対応（検証 → 見直し → 修正 → 反映 → 公開 → 返信） |
| `quiz-csv-format` | 自動発火 | Udemy 17カラム CSV の規約（定義元） |
| `research-cert-docs` | 自動発火 | ベンダー別の調査レシピと sources.md フォーマット（定義元） |
| `udemy-bulk-upload` | 自動発火 | Udemy のブラウザ操作レシピ（Claude in Chrome を第一手段・Playwright を代替。定義元） |

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
mode: mock-exam                             # 必須。mock-exam / mixed
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

### 任意キー: 解説の書式・用語集・出典の範囲

```yaml
style:                                      # 解説の書式の機械検査（check_style.py）。雛形で既定有効
  explanation_markers:                      # 各 Explanation の冒頭の正誤印（完全な先頭一致）
    correct: "正解です。"                   # false にすると正誤印の検査を止める
    incorrect: "不正解です。"
  require_space_after_source_url: true      # 出典 URL の直後に半角スペース
  # option_translation_marker / question_translation_marker / body_sentence_end /
  # translation_sentence_end は、問題文と解説の言語が違う講座（訳を併記）で使う
glossary:                                   # 原語で書く用語と、使ってはいけない訳語（check_style.py）
  - term: "<原語の用語>"
    forbid: ["<和訳>", "<カタカナ音写>"]    # Domain 列以外の全カラムで部分一致 → FAIL
    allow_context: ["<許す言い回し>"]       # 任意
source_scope:                               # ドメインごとの出典の許可範囲（check_sources.py）
  severity: warn                            # warn（既定）| fail
  include_primary_sources: true
  common:
    - docs.example.com/product-a/
  domains:
    D4:
      - docs.example.com/identity/
```

- **`style` が無い（または `{}`）と WARN。** それでも正誤印 x `Correct Answers` の整合だけは
  既定の印（先頭が「正解」/「不正解」、英語なら Correct / Incorrect）で検査します。
  正答の取り違えを落とす要なので、設定漏れで素通りさせません（実績: `style: {}` のまま運用し、
  正誤印の欠落33件と「不正解。」「不正解です。」の混在が全検査 OK のまま残った）
- **`glossary` は散文の方針の代わり。** 「製品名は原語のまま」と書くだけでは守られません
  （実績: 300問で約400件の和訳・カタカナ化・直訳調が混入）。作問ブリーフの契約文
  （`check_style.py --print-contract`）にも用語表が出ます
- **`source_scope` は同じホストの別製品ページを出典にした問題を拾います。** 出典欠落・禁止ホスト・
  到達確認はすべて通ってしまう欠陥クラスです（実績: 精読レビューまで2件残った）

### `mode: mixed` — 本ごとに問題数と配分が違う構成

本番が大問題数の試験では「分野別演習でドメインを絞って深く → フル模試で横断」の
段階構成が有効になる。その場合 `sections` が**本ごとの Source of Truth** になる。

```yaml
mode: mixed
questions_per_exam: 145        # フル模試1本の問題数（domains[].per_exam の合計）
sections:
  - slug: section01-drill-1    # フォルダ名そのもの
    title: 分野別演習① 基礎
    kind: drill                # drill=分野別演習 / mock=本番相当
    questions: 130
    minutes: 110
    domains: {D1: 70, D3: 60}  # 合計が questions と一致すること
  - slug: section04-mock-exam-1
    kind: mock
    questions: 145
    minutes: 100
    # domains 省略 = 全ドメイン横断（domains[].per_exam を使う）
```

`domain_quota(profile, "<slug>")` が本ごとのノルマを返す。**front matter を目で読んで
写さず、必ずスクリプトの出力を使う。** `mock-exam` モードも `section_specs()` が
同じ形で返すので、呼び出し側は mode を気にしなくてよい。

### 検証ルール

処理開始前に次を検証し、違反時は**推測で続行せず明示エラーで停止**します。

1. 必須キーの存在
2. `sum(domains[].per_exam) == questions_per_exam`
3. `domains[].id` の一意性
4. `mode` が `mock-exam` / `mixed` のいずれか
5. `mock_exams >= 1` かつ `questions_per_exam >= 1`
6. `mode: mixed` なら `sections` が存在し、各本の `domains` の合計が
   その本の `questions` と一致し、`domains[].id` が実在すること
7. `glossary` があれば各要素が `term`（文字列）と `forbid`（空でない文字列のリスト）を持つこと
8. `source_scope` があれば `severity` が warn / fail、各値がリスト、`domains` のキーが実在の
   ドメイン id であること（判定は `check_sources.py` と共通）

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

# 正解肢の長さバイアス検出（品質ゲート。シャッフル前に通す）
python scripts/check_option_balance.py section0*/quiz.csv

# 出典 URL のロケール正規化（冪等）
python scripts/normalize_urls.py section0*/quiz.csv

# パートの結合（日本語と英数字の間の半角スペースの割れを警告。--normalize で多数派に揃える。
# quiz.csv / quiz.raw.csv に _parts に無い手直しがあれば上書きせずに止まる。--force で上書き）
python scripts/merge_parts.py section01-mock-exam-1 --keep-parts

# 解説の整合・文体・訳・用語（正誤印 x Correct Answers / glossary の禁止訳語 / style の各規則）
python scripts/check_style.py section0*/quiz.csv --sections sections.md
python scripts/check_style.py --print-contract --sections sections.md   # 作問ブリーフの契約文

# 出典の検査（欠落・禁止ホスト・source_scope の範囲外。--check-urls で到達確認）
python scripts/check_sources.py section0*/quiz.csv --sections sections.md

# 選択肢シャッフル（原本退避 + 最良シード自動走査 + 位置分布検証）
python scripts/shuffle_options.py section01-mock-exam-1/quiz.csv
python scripts/shuffle_options.py section01-mock-exam-1/quiz.csv --check-drift   # 原本とのずれを見るだけ
python scripts/shuffle_options.py section01-mock-exam-1/quiz.csv --adopt         # quiz.csv の手直しを正とする

# 文面修正の前後で、正解・配分・選択肢数・出典 URL・正誤印が不変か（精読レビューの後に通す）
python scripts/check_invariants.py section0*/quiz.csv --sections sections.md    # 比較元は git HEAD
python scripts/check_invariants.py section01-mock-exam-1/quiz.csv --show 1-5    # 1問ずつ全カラム表示

# ドメイン配分・シラバス整合・本横断重複の検証
python scripts/validate_exam.py --sections sections.md \
  --bank question-bank.md section0*/quiz.csv

# あるキーワードが過去にどう問われたか（作問前に必ず見る）
python scripts/find_in_books.py オープン・イノベーション
python scripts/find_in_books.py Actor-Critic --answers-only

# ユーザー指定の必須収録が実際に入っているか（screening）
python scripts/check_must_include.py research/must-include.md
```

CSV の読み書きは `scripts/validate_quiz_csv.py` の `read_rows` / `write_rows` を使います（`utf-8` / BOM 無し / `newline=''` / `QUOTE_MINIMAL` が保証されます）。

## 設計上の判断

**payload と harness の分離。** 問題本文・ブループリント・プロジェクト方針は講座リポジトリ（payload）に、ワークフロー実装はこのプラグイン（harness）に置きます。プラグインを更新すれば全講座が同じ世代のハーネスを使います。

**判定ロジックをスクリプトに置く。** ドメイン配分・CSV 規約・重複・位置分布の判定は Python に実装して pytest で担保しています。エージェントの出力揺れに関係なく同じ基準が適用されます。スキルとエージェントはスクリプトを呼ぶだけで、検証ロジックを再実装しません。

**シャッフルは最良シード自動走査。** 単一固定シードは当たり外れが大きく、実績として seed=42 が正解を1位置に 78.8% 偏らせました。原本 `quiz.raw.csv` を退避して常に原本からシャッフルし（再シャッフルの罠の防止）、シードを走査して正解位置が最も均等になるものを採用します。

**原本とずれていたら上書きせずに止まります（raw ドリフト）。** `quiz.csv` を後から手直しすると原本が古いまま残り、原本から再シャッフルすると手直しが黙って消えます（実績: ある講座の6本すべてで、訳語の修正が `quiz.csv` にだけ入っていた）。比較は選択肢の並び順に依存しない指紋で行い、**どの選択肢が正解かも含めます**（`Correct Answers` だけの修正も検出する）。どちらを直したかは内容から判定できないので、`--adopt`（`quiz.csv` を正として原本を作り直す）/ `--force`（原本を正として手直しを捨てる）を明示させます。`finalize_section.py` は結合の直後なので `--adopt` で呼び、手直しの消失は結合前の `merge_parts.py` の検査が防ぎます。

**正誤印の判定は `check_style.py` と `check_invariants.py` で共通です。** 同じ解説を片方が通し片方が落とす食い違いを避けるため、判定関数（`marker_rule` / `read_verdict`）を1か所に置いています。

**期待票数は「その位置を提供した問題」からのみ積む。** 4択中心に5/6択が混在しても、位置5・6が誤検知になりません。

**長さバイアスはシャッフルでは消えない。** LLM は正解肢に根拠や仕組みの説明を書き込むため、正解が一貫して長くなります（実績: 45問で正解肢が2位の選択肢を平均 +29%・最大 +111% 上回っていた）。受講者が内容を読まずに「長いものを選ぶ」だけで正解できてしまう攻略可能な欠陥で、位置を変えても長さは付いてくるのでシャッフルでは解消できません。`check_option_balance.py` を**内容修正が可能なシャッフル前**の品質ゲートとして通します。

判定は **margin**（正解肢が2位の選択肢をどれだけ上回るか）で行います。「最長かどうか」の二値では、長さがほぼ揃った問題の統計的な同着まで欠陥として報告してしまいます（実測: 正解長が他の 1.03 倍でも 71% が「最長」になる）。受講者が知覚できるのは差の大きさなので margin で測り、1問ごとに +20% 以内、平均で +8% 以内、超過問題の割合 15% 以内を基準にします。

**multi-select も検査します。** 旧版は `multiple-choice` 以外を丸ごとスキップしていたため、multi-select の長さバイアスが無検査で通っていました（実績: ある講座の multi-select 42問のうち14問で正解肢がすべて最長、うち4問は「長い順に2つ選ぶ」だけで当たる本物の欠陥）。multi-select は**最も短い正解肢が最も長い誤答肢をどれだけ上回るか**で測ります。

**短い選択肢だけの問題は散らばりを免除します。** 用語名を裸で並べた形（本番でよくある）は散らばりが大きく出ますが、長い術語を選んでも正解にはならないので攻略可能性はありません。免除しないと悪化を招きます（実績: この停止を通すために作問エージェントが `FCN(モデル)` のような**意味のないタグで字数を稼いだ**のが20件）。代わりに**字数稼ぎタグそのものを検出**します。

**「URL は無いが出典はある」の判定を front matter から作ります。** `guide_citation` は資格ごとに表記が違う（`公式 Exam Guide（CODE）` / `JDLA 公式シラバス（…）`）ため、決め打ちの文字列で探すと別表記の資格でシラバス引用の問題が丸ごと「出典がない」と誤検出されます（実績: ある講座で約100件）。`check_sources.py` と `audit_course.py` は同じ `guide_pattern()` を使います。

**question-bank は追記ではなく貼り替えます。** 旧版は「既に追記済みならスキップ」でしたが、どちらの分岐も再実行で壊れました。スキップする側は確定後に問題を差し替えても**古い `tested_concept` が残り**、追記する側は判定を取りこぼすと**同じセクションの行が二重に入って**概念の再利用回数が倍になります。`refresh_bank()` はそのセクションの行を同じ位置で置き換えるので、何回実行しても結果が同じです。

**URL 正規化はホスト別の許可リスト方式。** ロケールがホスト直後の第1パスセグメントにあるサイト（`docs.claude.com/en/docs/...`）だけを書き換え、ロケールが下位にあるサイト（`code.claude.com/docs/en/...`）と未知のホストは一切触りません。前者の規則を後者に当てると `code.claude.com/en/docs/en/...` と URL を壊すためです。

## 既知の制約

- Udemy の演習テスト専用コースは**最大6テスト**。`mock_exams` は6以下にする
- コースが**有料設定済み**でないと演習テストを追加できない
- Udemy API は公開済みテストの個別問題を編集できない。**編集画面で問題ごとに書き換える**のが原則で、多数の問題は `scripts/udemy_sync_server.py` と `scripts/udemy_editor_helper.js` で自動化できる（`udemy-bulk-upload`）。テスト削除→再作成は最終手段
- 解説は Markdown を解釈されず、`**` が記号のまま表示される。`validate_quiz_csv.py` が FAIL にする。解説の改行の書式は警告で知らせる
- Udemy は CSV に BOM があるとヘッダー不正と判定する
- セクション構成は `mock-exam` のみ対応（トピック別構成は未対応）

## ライセンス

MIT
