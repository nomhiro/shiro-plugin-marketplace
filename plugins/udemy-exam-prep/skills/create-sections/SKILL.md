---
name: create-sections
description: 試験番号または学習ガイドURLを引数に、公式の学習ガイド/試験ガイドから sections.md を起草する。front matter の domains と primary_sources を確定させ、R1レビュー断面でユーザー承認を取ってから保存。スラッシュコマンド `/udemy-exam-prep:create-sections CCA-F` または「CCA-F の sections.md を作って」で起動。
---

# create-sections

ブループリント定義の **エントリーポイント**。公式の学習ガイドから `sections.md` を起草し、**R1レビュー断面**で必ず停止してユーザー承認を取ります。

## 起動例

```
/udemy-exam-prep:create-sections CCA-F
/udemy-exam-prep:create-sections CCA-F https://example.com/exam-guide
CCA-F の sections.md を作って
```

## なぜこのスキルが必要か

`sections.md` は **Source of Truth** で、ここが曖昧だと下流（[[doc-researcher]] / [[question-author]] / [[exam-validator]]）が全部歪みます。**明示的なレビュー断面**を設けることで、ドメイン構造の漏れ・曖昧さを最初に潰します。

前提として [[init-exam-course]] が実行済みで、`sections.md` の骨組み（front matter の一部と TODO マーカー）が存在していること。

## パイプライン

### Step 1: 引数と既存 front matter の読み取り

引数 `$ARGUMENTS` を解析する。

| 形式 | 例 | 動作 |
|------|-----|------|
| 試験番号のみ | `CCA-F` | `sections.md` front matter の `study_guide` を使う |
| 試験番号 + URL | `CCA-F https://...` | URL を優先し、`study_guide` を上書きする |
| 引数なし | | `sections.md` の `cert` と `study_guide` を使う |

既存の front matter を読む。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/profile.py" sections.md
```

この時点では `domains` 未確定なので FAIL（exit 1）が正常。`cert` / `vendor` / `study_guide` / `mock_exams` / `questions_per_exam` の値を確認する。

### Step 2: 学習ガイドの取得

`vendor` に応じた情報源から取得する（詳細なレシピは [[research-cert-docs]]）。

- **PDF 配布型**（`anthropic` など）— PDF を `research/` に保存し `pdfplumber` でテキスト化してから読む。WebFetch では表構造が落ちることがある
- **Web ページ型**（`microsoft` / `github` / `cloudflare`）— `WebFetch` または MCP 検索で取得

`WebFetch` のプロンプト例:

> 「この試験ガイドのスキル領域（ドメイン）とそのウェイト（%）、各ドメイン配下のタスクステートメントとその Knowledge of / Skills in の箇条書きを、個別の箇条書きレベルまで漏れなく構造化して抽出してください。試験概要（試験コード・問題数・所要時間・合格スコア・出題言語）と、In-Scope / Out-of-Scope の一覧も含めてください。」

### Step 3: 構造化抽出

取得したガイドから以下を抽出する。

- 試験概要: 試験コード / 問題数 / 所要時間 / 合格スコアとスケール / 出題言語 / 受験料 / 有効期限
- ドメイン: ID・正式名・ウェイト（%）
- 各ドメインのタスクステートメント（またはサブトピック）と、その配下の全箇条書き
- シナリオ（シナリオベース出題の資格のみ）
- In-Scope / Out-of-Scope の一覧

**ドメインの正式名は公式表記をそのまま使う。** この文字列が `quiz.csv` の `Domain` 列にそのまま入り、`exam-validator` の判定キーになる。訳したり短縮したりしない。

### Step 4: ドメイン別ノルマの算出

`questions_per_exam` をウェイト比で按分し、**合計が `questions_per_exam` と完全一致する整数**に丸める。

```python
# 例: questions_per_exam=60、ウェイト 27/18/20/20/15
# 素の按分: 16.2 / 10.8 / 12.0 / 12.0 / 9.0
# 丸め:     16   / 11   / 12   / 12   / 9   = 60
```

丸めの原則:
1. まず四捨五入する
2. 合計が合わなければ、**ウェイトが大きいドメインから ±1** して合わせる
3. どのドメインも 1 以上にする

このハーネスは**2つのモード**を持つ。`mode` は初期化時に決まっているので、**起草の前に front matter を読んで確認する。**

| mode | 構成 | 使いどころ |
|---|---|---|
| `mock-exam`（既定） | `mock_exams` 本のフル模試。**全本同じ問題数**で各本が全ドメインを横断（parallel forms） | 本番の問題数がそのまま6本ぶん作れる規模のとき |
| `mixed` | 本ごとに問題数・時間・ドメイン配分が違う。**`sections` が本ごとの Source of Truth** | 本番が大問題数で、分野別演習 → フル模試の段階構成にしたいとき |

### mixed モードの起草手順（Step 4 のあとに行う）

`domains` を確定させたら、`sections` を**全件明示的に**書く。

```yaml
sections:
  - slug: section01-drill-1        # フォルダ名そのもの
    title: 分野別演習① AI基礎・機械学習
    kind: drill                    # drill = 分野別演習 / mock = 本番相当
    questions: 130
    minutes: 110
    domains: {D1: 70, D2: 60}      # 合計が questions と一致すること
  - slug: section04-mock-exam-1
    title: 模擬試験 第1回
    kind: mock
    questions: 145
    minutes: 100
    # domains 省略 = 全ドメイン横断（domains[].per_exam をそのまま使う）
```

原則:

1. **`mock` 枠は `domains` を省略する。** 省略時は `domains[].per_exam` が使われるので、
   `questions` は `per_exam` の合計（= `questions_per_exam`）と一致していなければならない
2. **`drill` 枠は `domains` を明示する。** 絞ったドメインの合計を `questions` に一致させる
3. **`drill` 枠の配分は、そのドメインの `ratio` の比で按分する**（丸めは Step 4 と同じ原則）
4. **各ドメインの累計が枯れないか確認する。** `sections` 全体での
   ドメイン別合計（`profile.py` の出力に出る）が、そのドメインの素材量に対して
   多すぎないかを見る。1ドメインに数百問を割り当てると作問が破綻する
5. `slug` は**フォルダ名として実在させる**（`create-section` と `audit_course` がこの名前で引く）

検証はスクリプトが行う。**`sections` の合計や未知の domain id は `profile.py` が落とす。**

### Step 5: フォルダ名の確定

mock-exam モードのフォルダ名は固定命名。内容ベースのスラッグは生成しない。

| セクション | フォルダ名 |
|-----------|----------|
| Practice Test 1 | `section01-mock-exam-1` |
| Practice Test N | `section0N-mock-exam-N` |

### Step 6: front matter の確定と本文の起草

**front matter を更新する（ここが Step 6 の主目的）:**

```yaml
domains:
  - id: D1
    name: <公式表記のドメイン名>
    ratio: "27%"
    per_exam: 16
  # ... 全ドメイン
primary_sources:
  - priority: 1
    tool: local-file
    scope: research/<CERT>-Exam-Guide.txt（ブループリントの Source of Truth）
  - priority: 2
    tool: WebFetch
    scope: <公式ドキュメントサイト> — <対象領域>
```

`exam.language` / `question_types` / `scenario_ratio_min` / `max_per_concept` も、抽出した試験仕様に合わせて更新する。

**本文を起草する（まだファイルに書かない）:**

```markdown
# {試験番号} 演習テスト目次

> Source of Truth / 学習ガイド: {ガイドURL}
> 試験概要: {問題数}問 / {所要時間}分 / 合格{合格スコア} / {出題言語}
> 最終更新: {YYYY-MM-DD}

## 試験ブループリント（トピックユニバース）

### D1: {D1正式名} ({ウェイト})

#### 1.1 {タスクステートメント名}

**Knowledge of:**
- {箇条書きを漏れなく}

**Skills in:**
- {箇条書きを漏れなく}

#### 1.2 ...

## 配分表

| ドメイン | 名称 | ウェイト | 1本あたり | {N}本合計 |
|---|---|---|---|---|
| D1 | {正式名} | 27% | 16 | 96 |
| | **合計** | 100% | **60** | **360** |

### タスクステートメント × 1本あたり問題数

| ドメイン | タスクステートメント | 1本 | {N}本計 |
|---|---|---|---|

## シナリオ

（シナリオベース出題の資格のみ。各シナリオの production context とドメイン親和性）

## In-Scope / Out-of-Scope

### In-Scope
- {公式の一覧}

### Out-of-Scope（ここからは1問も作らない）
- {公式の一覧}

## セクション一覧

| セクション | フォルダ | 役割 | ステータス |
|---|---|---|---|
| Practice Test 1 | section01-mock-exam-1 | フル模試（全ドメイン縮図） | 未着手 |
```

### Step 7: ★ R1 レビュー断面 ★

**ここで必ず停止する。** 先に front matter の機械検証を通してから提示する。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/profile.py" sections.md
```

`OK:` が出るまで直す。そのうえでユーザーに以下を提示する。

```
sections.md を起草しました。保存前にレビューをお願いします。

【front matter 検証】
（profile.py の出力をそのまま貼る）

【試験概要】
- 試験コード / 問題数 / 所要時間 / 合格スコア / 出題言語 / 学習ガイドURL

【ドメイン構造】
- D1 (27%): {正式名} → 16問/本 ・ タスクステートメント {n} 個
- ...
セクションフォルダ: section01-mock-exam-1 〜 section0{N}-mock-exam-{N}（固定命名）

【プレビュー】
（sections.md 全文を表示）

【確認ポイント】
1. ドメインとウェイトが公式ガイド準拠か
2. タスクステートメントと箇条書きが公式ガイドすべてに対応しているか（網羅性）
3. front matter 検証5項目が通っているか
   - 必須キーの存在 / per_exam 合計 = questions_per_exam / domain id 一意 / mode / mock_exams・questions_per_exam >= 1
   - `mode: mixed` なら追加で: `sections` の件数 = `mock_exams` / slug 一意 / kind が drill|mock /
     各本の `domains` 合計 = その本の `questions` / `domains` 省略時は `questions` = per_exam 合計 / 未知の domain id なし
4. 配分表の合計が1本={questions_per_exam}問・{N}本={合計}問になっているか
5. Out-of-Scope が転記されているか

修正が必要なら指示してください。問題なければ「承認」または「OK」とお答えください。
```

ユーザー応答パターン別の動作:

| ユーザー応答 | 動作 |
|------------|------|
| 「承認」「OK」「進めて」 | Step 8 に進む |
| 「ドメイン2のサブトピックXが抜けてる」など修正指示 | 修正してから再度プレビュー → 再レビュー |
| 「キャンセル」「中止」 | 保存せず終了 |

### Step 8: sections.md をファイルに保存

承認を得たら `sections.md` として保存する。Bash heredoc ではなく Write tool で直接書く。

保存後に再検証する。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/profile.py" sections.md
```

### Step 9: CLAUDE.md との整合確認

プロジェクト `CLAUDE.md` の記述が `sections.md` と矛盾していないか確認する。`CLAUDE.md` はドメイン表を持たず front matter を参照する作りなので、通常は更新不要。資格固有の方針（出題言語・Out-of-Scope・用語表記）を追記すべき場合はユーザーに提案する。

### Step 10: 次ステップの提示

```
sections.md 作成完了

次のステップ:
- Phase 1a: doc-researcher による共有 digest の生成（/udemy-exam-prep:create-section 1 の内部で初回のみ実行）
- /udemy-exam-prep:create-section 1 で section01 から問題集作成を開始
- セクション順は問わない（特定のセクションから始めても OK）

各セクション作成時は doc-researcher 並列調査（共有digest）→ question-author 起草（ドメイン別ノルマ）
→ exam-validator（配分/シラバス外/重複検証）→ 選択肢シャッフル が自動実行されます。
最初の数問が生成された時点で R2 レビュー断面が入り、解説スタイルを確認できます。
```

## エラー時の対処

| 症状 | 対処 |
|------|------|
| 学習ガイドURLが404 | 試験番号を確認。ベータ試験は URL 形式が異なる場合あり。認定ページから辿る |
| 構造化抽出でサブトピックが拾えない | WebFetch のプロンプトを「全箇条書きを漏れなく」と明示して再試行。PDF ならテキスト化して直接読む |
| ウェイト%が抽出できない | 認定資格ページ（study-guide ではなく certification ページ）を併用 |
| `per_exam` の合計が合わない | Step 4 の丸め原則2でウェイト最大のドメインから調整 |
| ドメイン名が長い/短いブレ | 公式ガイドのオリジナル表現に統一（`Domain` 列の値になるため厳密に） |
| PDF が WebFetch でリンクしか返らない | ページの全リンク列挙を頼んで PDF の直 URL を得てから `curl -sL` で落とす |

## 厳守ルール

1. **R1レビュー断面で必ず停止** — ユーザー承認なしに `sections.md` を保存しない
2. **保存前後に `profile.py` を通す** — 目視確認で済ませない
3. **タスクステートメントと箇条書きを公式ガイドから漏れなく拾う** — ここが出題概念の母集団になる
4. **公式ガイドの原文を改変しすぎない** — 表現はオリジナルに準拠（独自解釈で書き換えない）
5. **ドメイン正式名は公式表記のまま** — `quiz.csv` の `Domain` 列と `exam-validator` の判定キーになる
6. **Out-of-Scope を必ず転記する** — 出題範囲外の混入を防ぐ最後の砦
7. **取得日を最終更新欄に記録** — `sources.md` と同じ運用

## 関連スキル

- 前に呼ぶスキル: [[init-exam-course]] — プロジェクトの初期化
- 次に呼ぶスキル: [[create-section]] — セクション単位の問題集作成
- 補助スキル: [[research-cert-docs]] — ベンダー別の調査レシピ
