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

#### Step 4c: 残り問題の生成（ドメイン別の並列 + パートファイル）

サンプル承認後、**ドメインごとに question-author を並列起動する**。同じメッセージ内に複数の
Agent tool 呼び出しを置く。1ドメインあたり10〜16問なのでコンテキストが軽く、全体が速い。

**各エージェントには `quiz.csv` を直接書かせてはいけない。** 並列で同じファイルに書くと
読み込み→書き戻しで競合し、片方の成果が消える。**パートファイル方式**を使う。

| エージェントの出力 | 内容 |
|---|---|
| `<folder>/_parts/<ドメインID>.csv` | 担当ドメイン分だけの17カラム CSV（ヘッダーあり） |
| `<folder>/_parts/<ドメインID>-meta.tsv` | CSV と同順・ヘッダーなし・タブ区切り6列（`連番` / `ドメインID` / `task_statement` / `tested_concept` / `scenario` / `問題文の冒頭60字`） |

結合はスクリプトが決定的に行う（`front matter` の `domains` 順に並べ、通し番号を振る）。

**共通の作問契約は1つのブリーフに書いて渡す。** 各エージェントのプロンプトに同じ2,500トークンを
コピーすると、指示のずれと待ち時間が増える。`init-exam-course` が展開する
`.work/AUTHOR-BRIEF.md` に共通事項（出題言語・選択肢の長さ基準・解説の書き方・出典の書き方・
重複回避・出力形式・自己チェック）を書き、各プロンプトは**担当ドメイン・問題数・配分・
読む digest・そのドメイン固有の注意**だけにする。

各エージェントへの個別指定:
- 担当ドメインID と `Domain` 列に書く正式名
- 問題数、task_statement 別の配分、`multiple-choice` / `multi-select` の数、シナリオ別の配分
- 読む digest のパス
- `used_concepts.py --all` の出力（**全ドメインの**既出概念。下記）
- **所有表の除外リストを全件**（`research/AUTHORING-GUARDRAILS.md`。下記）

**既出概念の一覧は機械生成して渡す。** 手書きでプロンプトに貼るのは維持できない。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/used_concepts.py" --all --out .work/used-all.md
```

**`--all` を使う（担当ドメインだけを切り出して渡さない）。** ドメイン別に渡すと
他ドメインが所有する概念が構造的に見えず、重複がそのまま通る。

> 実績: ある講座の6本目で見つかった重複6件は**すべて他ドメインの履歴にある重複**だった。
> 5.2 の問題が 2.4 の既出と衝突、5.4 が 2.3 と、6.1 が 5.1 と、2.5 が 3.1 と、
> 2.3 が 4.1 と 5.1 と。担当エージェントからは1件も見えていなかった。

**`--out` を使う（シェルのリダイレクトを使わない）。** `>` で書くと Windows では
既定コードページ（cp932）で保存され、読み手が壊れた内容を受け取る
（実績: 8ファイルすべてが cp932 になり作問エージェントが読めなかった）。

上限に達した概念が何件あるかを確認し、**残り枠が必要問題数を下回っていないか**を先に見る。

### 除外リストは全件載せる（ドメインごとに抜粋しない）

`research/AUTHORING-GUARDRAILS.md` に「論点の所有スキル」表を作り、
**その全件**を各エージェントのプロンプトに載せる。担当ドメインに関係しそうな行だけを
抜粋すると伝え漏れが起きる。

> 実績: 「1リクエストの画像/文書ページ数上限」を D5 のプロンプトには書いたが
> D2 には書かず、D2 がその論点で出題して差し替えになった。しかも
> **正解肢の類似度は 41% で、閾値を下げた文面照合でも検出できなかった**
> （問い方が `root-cause` の診断と記述選択で違うため文面が散る）。
> 数値事実の重複は**所有表だけが防げる**。

完了後 `quiz.sample.csv` は削除する（サンプルは担当ドメインのパートに取り込ませる）。

### Step 5: 品質ゲート（シャッフル前に必ず通す）

**工程順は `finalize_section.py` が固定している。** 個別に叩くより、これ1本で通すほうが
順序の取り違えと工程の飛ばしを防げる（11工程・失敗したらそこで停止）。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/finalize_section.py" <folder>
```

工程: パート結合 → CSV 整合性 → 出典検査 → **長さバイアス** → URL 正規化 →
ドメイン配分 → question-bank 追記 → 本横断の重複 → シャッフル → CSV 再検証 → 統計。

以下は各工程を個別に確認したいときの内訳。**どれも飛ばしてはいけない。**

パートを結合して `quiz.csv` を作る（配分・`Domain` 列・meta 行数を同時に検証する）。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/merge_parts.py" <folder> --keep-parts
```

CSV 整合性を検証する。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_quiz_csv.py" <folder>/quiz.csv
```

解説の整合・文体・訳を検証する。**形式検証では「正解番号が誤答肢を指している」を
検出できない**（インデックスが範囲内で個数が正しければ通るため）。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py" <folder>/quiz.csv --sections sections.md
```

front matter に `style` が無ければ自動でスキップされる。設定すると
正誤印 x `Correct Answers` の整合・訳マーカーの有無・解説本体と訳の文体・
出典 URL 直後の半角スペースを検査する。

出典を検査する（出典の欠落と、front matter の `forbidden_sources` に挙げたホストの混入）。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_sources.py" <folder>/quiz.csv --sections sections.md
```

**正解肢の長さバイアスを検査する。内容修正を伴うので必ずシャッフル前に通す。**

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_option_balance.py" <folder>/quiz.csv
```

正解肢が体系的に長いと、**受講者は問題文を読まずに「長い選択肢」を選ぶだけで正解できる**。
実績として、ある講座の1本目は MC 90問中70問（78%）で正解肢が最長だった。位置を
シャッフルしても長さは付いてくるので、シャッフルでは解消できない。FAIL したら
**不正解肢に具体的な実装内容を書き込んで長さを揃える**か、**根拠の説明を `Explanation` 側へ移す**。

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

`<folder>/sources.md` は生成する（手書きしない）。`quiz.csv` と `_parts/bank-rows.md` から
出典一覧と問題ごとの対応表を作る。ホストの表示名と Exam Guide 出典の表記は front matter の
`source_titles` / `guide_citation` から読む。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/make_sources_md.py" <folder> --sections sections.md
```

**最後の本を作り終えたら、講座全体を横断監査する。**

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/audit_course.py"
python "${CLAUDE_PLUGIN_ROOT}/scripts/audit_course.py" --check-urls   # URL 到達も確認（時間がかかる）
```

セクション数・総問題数・ドメイン別累計・タスクステートメント網羅・問い方の型の分布・
概念の再利用回数・正解位置の分布・出典ホスト・問題文の横断類似（82%）・
正解肢の横断類似（45%）・`tested_concept` ラベルの近似（55%）・
**創作識別子の衝突**をまとめて見る。

**FAIL と WARN は意味が違う。**

| 区分 | 内容 | 対応 |
|---|---|---|
| **FAIL** | 配分の不一致・概念の上限超過・問題文 82% 以上・正解肢 80% 以上・**創作識別子の衝突** | 直すまで先に進まない |
| **WARN** | 正解肢 45〜80%・ラベル 55% 以上 | **人が見て許容か差し替えかを判断する** |

`--strict` を付けると WARN も失敗として扱う。

> **低い閾値の検出をそのまま FAIL にしてはいけない。** レビューで許容した隣接まで
> 赤くなり「監査を無視する習慣」を作る。実績として、318問すべてが目標どおりの講座で
> WARN 14件（うち11件はレビュー済みの許容）・FAIL 0件という状態になった。

> **正解肢の類似検査は概念レベルの重複検査とは別物。** `tested_concept` のラベルを
> 言い換えれば概念検査は通るが、**正解として提示する事実の文面が同じなら、先の本を
> 解いた受講者は見覚えだけで正解できる**。
>
> **さらに、数値事実の重複はどの文面照合でも捕まらない。** 実績: 同じ規則
> （1リクエストの画像/文書ページ数上限）を、一方は `root-cause` の診断、
> 他方は記述選択で出題したところ**正解肢の類似度 41%** で、45% でも検出できなかった。
> これを防げるのは `research/AUTHORING-GUARDRAILS.md` の**所有表**と、
> 「既存本の正解肢だけを抽出して候補の事実を照合する」手順だけである。

### Step 9: 一時ファイルの後始末（機械的）

エージェントはリポジトリ直下や `research/` に作業用スクリプト・スクラッチを残すことがある（実績: `gen_quiz_*.py` 等が6本残留）。R3 提示前に**オーケストレータ側で機械的に掃除**する（エージェントの自己申告に頼らない）。

```bash
rm -f ./*.py
rm -f <folder>/quiz.sample.csv
rm -f research/*-check.txt research/*.tmp
```

**パートファイルは結合後に削除してよい**（`_parts/bank-rows.md` は残す）。内容は
`quiz.raw.csv`（結合済み・シャッフル前）と `bank-rows.md` で保全される。
`.gitignore` に `**/_parts/D*.csv` と `**/_parts/*-meta.tsv` を入れておく
（`init-exam-course` が展開する `.gitignore` に含まれている）。

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
