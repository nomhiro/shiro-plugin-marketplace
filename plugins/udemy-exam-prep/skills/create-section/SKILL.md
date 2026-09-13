---
name: create-section
description: セクション番号を引数に、quiz.csv と sources.md を一括作成・更新するパイプライン。doc-researcher を並列起動 → question-author で生成（ドメイン別ノルマ・question-bank 渡し）→ exam-validator で配分・シラバス外・重複検証 → 出典URL正規化 → 選択肢シャッフル（最良シード自動走査・分布検証付き）。スラッシュコマンド `/udemy-exam-prep:create-section <N>` または「セクションNの問題集を作って」で起動。
---

# create-section

セクション `$ARGUMENTS` の問題集（quiz.csv + sources.md）を作成または更新するための**オーケストレータスキル**です。実装の詳細は個別の skill / agent / script に委譲します。

## 起動例

```
/udemy-exam-prep:create-section 2
セクション2の問題集を作って
section02 のクイズを更新して
```

## 前提

- `sections.md` が存在し、front matter が検証を通ること
- `question-bank.md` / `removed-questions.md` が存在すること（[[init-exam-course]] が作る）

## パイプライン

### Step 1: セクション情報と試験プロファイルの取得

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/profile.py" sections.md
```

`OK:` が出ることを確認し、出力から以下を得る。

- `questions_per_exam` — このセクションの目標問題数
- `quota` — ドメイン別ノルマ（`{'D1': 16, 'D2': 11, ...}`）
- `mock_exams` — 全体の本数

`sections.md` 本文から以下も読む。

- 対象セクションのフォルダ名（例: `section02-mock-exam-2`）
- タスクステートメント × 1本あたり問題数の割当表
- シナリオとドメイン親和性
- `domains[].name`（`Domain` 列に書く正式名）
- Out-of-Scope の一覧

**FAIL が出たら先に進まない。** front matter の不備は下流すべてを歪める。

### Step 2: doc-researcher を並列起動（初回のみ全シラバス調査）

**初回のみ:** `sections.md` のブループリント（全ドメイン×全タスクステートメント）を対象に [[doc-researcher]] を並列起動し、調査結果を `research/` 配下に保存する。**同じメッセージ内に複数の Agent tool 呼び出しを置いて並列実行**する。

各エージェントへの入力:
- 資格名と試験番号、担当する技術領域と対応するタスクステートメント番号
- `sections.md` の該当ドメイン節（`Knowledge of` / `Skills in` の箇条書き）
- front matter の `primary_sources`
- **Out-of-Scope の一覧**（この範囲の事実は digest に入れない）
- 出力先パス
- 既調査の `sources.md` があれば既知 URL 一覧（重複回避）

各エージェントは [[research-cert-docs]] に従って調査し、digest を `research/<領域>.md` として保存する。

**2回目以降:** `research/` の共有 digest を参照する（再調査しない）。

調査後にカバレッジを機械確認する。

```bash
for f in research/*.md; do
  echo "$f : URL=$(grep -cE 'https?://' "$f") lines=$(grep -c '' "$f")"
done
```

URL=0 の digest は推測で書かれている疑いがあるので再実行する。

### Step 3: digest の集約

`research/` の digest を読み込む。`sources.md` の **参照ドキュメント一覧** はこの時点で確定できる。

### Step 4: question-author を **2フェーズ** で起動

サンプルレビューを挟むため、question-author は2段階で動かす。

#### Step 4a: サンプル生成（3〜5問）

[[question-author]] を **サンプルモード** で起動する。入力:

- セクション番号、出力先（一時ファイル `<folder>/quiz.sample.csv`）
- digest 群（Step 3 の集約結果）
- **ドメイン別ノルマ**（Step 1 の `quota`）
- タスクステートメント割当表、シナリオとドメイン親和性
- **`question-bank.md` のパス**（既出概念インデックス）
- 目標問題数: 4（サンプル）
- 多様性を意図的に確保: `multiple-choice` 2問 + `multi-select` 2問、シナリオ問題を必ず含める
- 既存 `quiz.csv` は触らない

エージェントは [[quiz-csv-format]] に従う（解説スタイルは question-author に内包）。

#### Step 4b: ★ R2 レビュー断面 ★

**ここで必ず停止する。** ユーザーに以下を提示する。

```
section{N} の最初のサンプル4問を生成しました。スタイル確認をお願いします。

【サンプル問題プレビュー】
─────────────────────────────
[Q1] multiple-choice / シナリオ: S1 / task_statement: 1.4 / Domain: {正式名}
tested_concept: ...
問題文: ...
選択肢:
  1. ... | 解説: ...
  2. ... | 解説: ...（正解）
  3. ... | 解説: ...
  4. ... | 解説: ...
Overall Explanation: ... | 出典: ...
─────────────────────────────
...

【確認ポイント】
1. 解説が「教材レベル」（不正解の選択肢も何を意味するかを説明している）か
2. 不正解の選択肢が「一見妥当なアンチパターン」になっているか（明らかな誤りの羅列でないか）
3. 問題文の末尾で問われる観点が明示されているか（根本原因 / 最善の第一手 / コスト最適 など）
4. シナリオ問題が現場感のあるものか
5. 出典URLが具体的なディープリンクか
6. 難易度が公式サンプル問題と同等か（定義問題になっていないか）
7. Domain 列が front matter の domains[].name のいずれかと完全一致しているか
8. task_statement と tested_concept が申告されているか

修正が必要なら指示してください。問題なければ「承認」とお答えください。
```

| ユーザー応答 | 動作 |
|------------|------|
| 「承認」「OK」 | Step 4c に進む |
| 「解説をもう少し詳しく」など方針修正 | 解説スタイル指示を強化して再生成 → 再レビュー |
| 「QN のドメインタグが違う」 | digest を見直し該当問題を修正して再生成 |
| 「全部やり直し」 | Step 4a からやり直し |
| 「キャンセル」 | `quiz.sample.csv` を削除して終了 |

#### Step 4c: 残り問題の生成

サンプル承認後、question-author を **残り問題数モード** で起動する。

- 目標問題数: `questions_per_exam` − サンプル数
- サンプル `quiz.sample.csv` を「スタイル基準」として渡す
- **ドメイン別ノルマ**と**タスクステートメント割当表**を渡す
- **`question-bank.md`** を渡す（重複回避）
- 既存 `quiz.csv` があればマージ
- 出力先は `<folder>/quiz.csv`（サンプルもマージして含める）

ドメイン単位で分割起動すると各エージェントのコンテキストが軽くなる。分割する場合は**起動ごとに `question-bank.md` の最新状態**を渡す。

完了後 `quiz.sample.csv` は削除する（`quiz.csv` に取り込み済み）。

### Step 5: 品質ゲート（シャッフル前に必ず通す）

まず CSV 整合性を検証する。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_quiz_csv.py" <folder>/quiz.csv
```

次に [[exam-validator]] を起動する。入力: 対象セクション番号 / `quiz.csv` / `sections.md` / `question-bank.md` / `removed-questions.md`。

exam-validator は以下を検証する。

1. **CSV整合性** — 17カラム / 正解数 / 正解インデックス範囲 / `multi-select` の distractor 有無 / 必須列
2. **ドメイン配分** — front matter の `per_exam` ノルマを満たすか
3. **問題タイプ比率** — front matter の `question_types` の範囲に入るか
4. **シラバス外検出** — ブループリント外・Out-of-Scope の問題を `removed-questions.md` に退避
5. **本横断の重複** — `question-bank.md` の既出 `(task_statement, tested_concept)` との突き合わせ

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_exam.py" --sections sections.md \
  --bank question-bank.md <folder>/quiz.csv
```

配分不足・重複・タイプ比率不足・distractor 無しが報告された場合は是正し、再実行するループを繰り返す（全クリーンまで）。

> **品質ゲートはシャッフル（Step 7）前に通すこと。** distractor 無し・タイプ比率不足は内容修正を伴うため、シャッフル後に発覚すると原本 `quiz.raw.csv` 修正＋再シャッフルの手戻りになる（実績あり）。Step 5 で必ず確定させる。

> **微小な外科的 CSV 修正はオーケストレータが直接行う。** distractor 化のために1選択肢を誤答へ書き換える・`Domain` セルを再タグするといった機械的修正は、サブエージェントに委譲せずオーケストレータが Python で直接編集してよい。サブエージェントは安全機構により「コーディネーター経由の承認」を受け付けず作業を拒否して停止することがある（実績あり）。判断不要の小修正で round-trip を増やさない。原本 `quiz.raw.csv` が既にある場合はそちらを編集し、Step 7 を再実行して反映する。

### Step 6: 出典URLの正規化（機械的）

出典 URL の英語版ディープリンク化は**モデルの記憶に頼らず機械的に保証**する（生成時の付け忘れが実際に発生している）。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/normalize_urls.py" <folder>/quiz.csv
```

冪等。既知ホスト（`docs.claude.com` / `learn.microsoft.com` / `docs.github.com` 等）のロケールセグメントを英語版に揃え、ロケールを持たないサイトと未知ホストは触らない。

### Step 7: 選択肢シャッフル（最良シード自動走査）

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/shuffle_options.py" <folder>/quiz.csv
```

このスクリプトは次を行う。

1. 原本 `<folder>/quiz.raw.csv` を**一度だけ**退避する（既にあれば触らない）
2. 常に**原本から**シャッフルする
3. シード1〜500を走査し、正解位置の最悪相対偏差が最小のシードを採用する
4. 位置ごとの実測票数と期待票数を表示する

**重要:**
- **`quiz.csv` を読んで `quiz.csv` に書き戻す旧方式は禁止。** 再ロール時に「一度混ぜた後」を再シャッフルしてしまい再現性が壊れる（再シャッフルの罠）
- 単一固定シードは使わない。**実績として seed=42 が正解を1位置に 78.8% 偏らせた**
- `quiz.raw.csv` は意図的に残す（再ロール用）。Step 9 のクリーンアップでも削除しない
- 偏りが残る場合は `--max-seed 2000` に広げる。それでもダメなら選択肢数のばらつきや正解選択肢の表現を見直す

### Step 8: 分布検証（独立再検証）と sources.md

シャッフル出力の判定基準:

- 各位置の実測票数が**期待票数 ±20%（最低でも絶対 ±1.5 票）** 以内
- 期待票数は「その位置を実際に提供した問題」からのみ積む厳密モデル。4択中心に5/6択が混在しても位置5・6が誤検知にならない
- `WARN:` が1件も出なければ合格

`<folder>/sources.md` を [[research-cert-docs]] の「sources.md フォーマット」に従って書き出す。exam-validator でシラバス外問題を退避した場合は問題番号を振り直す。

### Step 9: 一時ファイルの後始末（機械的）

エージェントはリポジトリ直下や `research/` に作業用スクリプト・スクラッチを残すことがある（実績: `gen_quiz_*.py` 等が6本残留）。R3 提示前に**オーケストレータ側で機械的に掃除**する（エージェントの自己申告に頼らない）。

```bash
rm -f ./*.py
rm -f <folder>/quiz.sample.csv
rm -f research/*-check.txt research/*.tmp
```

**保持するもの（削除しない）:** 各セクションの `quiz.csv` / `sources.md` / **`quiz.raw.csv`（再ロール用の原本）**、`research/*.md`（共有 digest）、`question-bank.md`、`removed-questions.md`。
※ ルート直下にプロジェクト管理用の `.py` を恒久的に置く運用をする場合は、ファイル名を限定して消すこと。

### Step 10: ★ R3 レビュー断面 ★

生成・検証・正規化・シャッフルがすべて完了した時点で、**集約レポートを提示して最終承認を取る**。

```
section{N} の問題集生成パイプラインが完了しました。

【生成結果】
- 出力: <folder>/quiz.csv ({N}問)
- 出力: <folder>/sources.md ({M}出典)
- 原本: <folder>/quiz.raw.csv（再ロール用に保持）

【内訳】
- multiple-choice: X問 (Y%) / multi-select: Z問 (W%)
- シナリオ別: S1 x問 / S2 x問 / ... / S6 x問

【ドメイン配分】
（validate_exam.py の出力をそのまま貼る）

【シラバス外／重複】
- シラバス外退避: K問 → removed-questions.md
- 重複: M問 → 再生成済み
- question-bank.md に N問を追記

【正解位置分布】
（shuffle_options.py の出力をそのまま貼る。採用シードと最悪相対偏差を含む）

【サンプル抜き打ち（3問）】
（ランダムに3問の全文）

確認ポイント:
1. 問題数が {questions_per_exam} 問か
2. ドメイン配分がノルマ通りか
3. 退避問題が想定外に多くないか（10%超ならブループリントを見直し）
4. 正解位置分布に WARN が出ていないか
5. サンプル抜き打ちで品質が許容できるか

問題なければ「承認」、修正が必要なら指示をください。
```

| ユーザー応答 | 動作 |
|------------|------|
| 「承認」「OK」 | Step 11 に進む |
| 「分布が偏ってる」 | Step 7 を `--max-seed 2000` で再実行（原本から走査するので決定的） |
| 「サンプルQXX の解説が薄い」 | 該当問題のみ question-author に再起草を依頼 |
| 「退避が多すぎる」 | `sections.md` のブループリント見直しを促す |
| 「やり直し」 | Step 4a から再実行 |

### Step 11: 最終レポート

承認を得たら以下を報告する。

- 生成された問題数（タイプ別内訳）
- ドメイン別配分
- シラバス外退避問題数 / 重複として再生成した問題数
- 正解位置分布（採用シードと偏差）
- `question-bank.md` に追記した問題数
- 出力ファイル
- 次ステップ: 他の模試も作成するか / Udemy アップロードに進むか

## 引数

`$ARGUMENTS` にはセクション番号を1つ指定する。自然言語で起動された場合は文脈から抽出する。

## エラー時の対処

| 症状 | 対処 |
|------|------|
| `profile.py` が FAIL | front matter を直す。ここを飛ばして進めない |
| doc-researcher が情報を集めきれない | 領域を2分割して別エージェントに再依頼 |
| digest に URL が無い | 推測で書かれている。再実行する |
| 問題数が目標に達しない | question-author を再起動し digest を追加して補完 |
| シラバス外が大量退避 | ブループリント定義が曖昧。`sections.md` 見直しを提案 |
| シャッフル後も偏りが残る | `--max-seed 2000` に拡張。それでもダメなら選択肢数のばらつきを見直し |
| サブエージェントが承認待ちで停止 | 判断不要の小修正はオーケストレータが直接 Python で行う |
| 概念の残り枠が足りない | `tested_concept` をより細かい粒度で切る（1つの箇条書きを複数の検証観点に分ける） |

## 注意事項

- 既存 `quiz.csv` がある場合はマージモードで動作（question-author に既存ファイル情報を渡す）
- `removed-questions.md` に該当セクション向けの問題があれば優先的に再利用
- Bash heredoc で CSV を書くのは事故りやすい → 必ず Python スクリプト経由（`write_rows` を使う）

## 関連スキル・エージェント

- 調査エージェント: [[doc-researcher]]
- 起草エージェント: [[question-author]]（解説スタイル内包）
- 検証エージェント: [[exam-validator]]
- [[quiz-csv-format]] — CSV 規約
- [[research-cert-docs]] — 調査レシピ
