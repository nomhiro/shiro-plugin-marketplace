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

- `questions_per_exam` — このセクションの目標問題数（**`mode: mixed` では本ごとに違う。下記参照**）
- `quota` — ドメイン別ノルマ（`{'D1': 16, 'D2': 11, ...}`）
- `mock_exams` — 全体の本数

### `mode: mixed` では本ごとのノルマをスクリプトから取る

本ごとに問題数もドメイン配分も違うので、**front matter を目で読んで写さない。**
`profile.py` が本ごとの仕様を一覧で出すので、担当セクションの行をそのまま使う。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/profile.py" sections.md
```

```
OK: G検定 / mode=mixed / 6 sections / 825 questions
  section01-drill-1      drill  130問 110分  quota={'D1': 70, 'D2': 60}
  section04-mock-exam-1  mock   145問 100分  quota={'D1': 20, 'D2': 25, ...}
```

**作問エージェントに渡すのはこの `quota` の値。** `merge_parts.py` と
`validate_exam.py` は**フォルダ名から本ごとのノルマを引く**ので、
セクションフォルダ名を front matter の `slug` と一致させておくこと
（一致しないと全体ノルマで検証され、配分違反を取り逃がす）。

`kind` によって作問の方針が変わる:

| kind | 方針 |
|---|---|
| `drill` | 担当ドメインを深く。同一ドメイン内で task_statement を網羅する。時間は緩めなので設問は長くてよい |
| `mock` | 全ドメイン横断。**本番相当の難易度と時間圧**を前提に、1問の読解量を抑える |

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

#### Step 2.5: ガードレールを埋める（初回のみ・これを飛ばすと4本目で詰まる）

digest がそろった時点で `research/AUTHORING-GUARDRAILS.md` の
**A〜K を埋める。** 雛形は [[init-exam-course]] が展開している。

**とくに K（論点の所有表）は Phase 1a の成果物として確定させる。**
後回しにすると、3〜4本目で「この数値事実はどのドメインの持ち物か」が
決まっていないまま出題が進み、遡って差し替えることになる。

```bash
# 所有表が空のまま作問に入っていないか確認する
grep -c '^| .* | D[0-9]' research/AUTHORING-GUARDRAILS.md
```

埋め方は雛形の K 節に書いてある。各 digest から「数値・上限・既定値・排他条件」の
ように一意に定まる事実を抜き、所有ドメインを1つに決める。

### Step 2.6: 作問ブリーフの文体契約を生成する（初回のみ・必須）

`style` の有無に関係なく**必ず生成して `AUTHOR-BRIEF.md` の §5-1 に貼り込む**
（正誤印の既定検査と `glossary` の禁止訳語は、`style` が無くても常に機械検査されるため）。
**`glossary` を確定させてから生成する。** 後から用語を足したら再生成して §5-1 を貼り替える。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py" --print-contract --sections sections.md
```

出力をそのまま §5-1（`（未生成）` と書かれた節）に置き換える。**散文で書き写さない。**

> **これを飛ばすと担当ドメインの全問が落ちる。** 実績: ある講座で
> `check_style.py` が正誤印・訳マーカー・本体と訳の文体・出典 URL 直後の
> 半角スペースを検査するのに対し、ブリーフ側にその基準が1つも書かれていなかった。
> 作問直前に気づいて貼り込んだが、気づかなければ**6本378問すべてが
> 書き直し**だった。

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

#### ★ 完了報告を成果物の存在の根拠にしない（機械確認する）

**エージェントが「完了」と報告してもファイルが無いことがある。**
報告してから書くエージェントがいるため、報告と実物がずれる。

```bash
# 全ドメインのパートがそろい、行数がノルマと一致しているかを一撃で見る
for f in <folder>/_parts/D*.csv; do
  echo "$f: $(($(grep -c '' "$f") - 1)) 行 / meta $(grep -c '' "${f%.csv}-meta.tsv") 行"
done
```

- **無い / 行数が足りないなら、そのドメインだけ再依頼する**（全体をやり直さない）
- **不一致を見つけても即座に「捏造」と判断しない。** 編集途中を読むと
  一時的に不整合に見える。**1回置いてから再確認する**
  （実績: 途中状態を読んで誤って不整合と報告し、撤回した）
- `merge_parts.py` は meta と CSV の行のずれを FAIL、head の古さを WARN で
  報告する。**WARN が出たら同じ行の `tested_concept` も古いと疑う**

#### ★ 作問エージェントに再委譲させない

作問エージェントが自分の fork へ委譲すると、**引き継ぎ先が停止しても
オーケストレータからは「稼働中」に見えたまま進まない**（実績: 2ドメインが停止）。
`AUTHOR-BRIEF.md` §10 に禁止として書いてあるが、**プロンプトでも明示する**。

#### ★ 「未使用かどうか」ではなく「どう問われたか」を渡す

`used_concepts.py` が出すのは `tested_concept` の**ラベル**で、
**どんな問題文・どんな正解肢だったかは見えない。** ここが重複事故の本体。

> 実績: ある講座のフル模試1本目で6件差し戻した。`オープン・イノベーション` は
> 分野別演習で出ていたのに**まったく同じ問題文**で再出題していた（類似度100%）。
> ラベルは別概念に見えていたので `used_concepts.py` では防げなかった。
> 原因は親の指示文が「この14キーワードは1観点しか使っていません」と書いたのを
> エージェントが「未使用」と読んだこと。**「未使用」と「1観点だけ使用済み」を
> 明確に区別して書く。**

作問エージェントには**扱うキーワードでこれを実行させる**。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/find_in_books.py" <キーワード>
python "${CLAUDE_PLUGIN_ROOT}/scripts/find_in_books.py" <キーワード> --answers-only
```

`★正解肢` に出ていたら**同じ答えを2回作らない**。誤答肢・解説だけなら主役にしてよい。

#### 必須収録の指定があるとき

受講者から「この問題は必ず入れて」と資料を渡された場合は、
**作問後に機械で突き合わせる**（目視では取りこぼす）。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_must_include.py" research/must-include.md
```

これは screening（既定では落とさない）。閾値未満の項目を人が確認する。
**必須収録の指定は自分の作問ルールより優先する。** 禁止論点と衝突したら
ユーザーの指定を通し、検査側に例外を書く（実績: 公式サンプル問題との
論点重複を避ける自前ルールが必須収録の1問と衝突し、例外を追加して収録した）。

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

`merge_parts.py` は**日本語と英数字の間の半角スペースの有無**が割れていると WARN を出す
（行ごとに判定し、少数派の行範囲をパート別に表示する。実績: 分割作問の前半25問と後半25問で
癖が割れた）。`--normalize` で多数派に揃う（パート CSV にも書き戻す。URL・バッククォート内・
`Domain` 列は触らず、URL 直後の半角スペースは消さない）。`finalize_section.py --normalize-spacing`
でも同じ。表記が割れたまま結合すると、講座内の表記ゆれとして後工程まで残るので、ここで揃える。

**結合し直すと消える手直しがあれば止まる。** `quiz.csv` / `quiz.raw.csv` に `_parts` に無い
手直しがあると、`merge_parts.py`（と `finalize_section.py`）は上書きせずに FAIL する。
手直しを `_parts/<ドメイン>.csv` に反映して結合し直すのが正。捨ててよいときだけ `--force`。

CSV 整合性を検証する。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_quiz_csv.py" <folder>/quiz.csv
```

解説の整合・文体・訳を検証する。**形式検証では「正解番号が誤答肢を指している」を
検出できない**（インデックスが範囲内で個数が正しければ通るため）。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_style.py" <folder>/quiz.csv --sections sections.md
```

正誤印 x `Correct Answers` の整合は、front matter に `style` が無くても**既定の印で検査される**
（`style` の設定漏れで正答の取り違えを素通りさせないため）。`style` を設定すると、
印の表記の統一・訳マーカーの有無・解説本体と訳の文体・出典 URL 直後の半角スペースも検査する。
front matter に `glossary`（原語で書く用語と禁止訳語）があれば、`Domain` 列以外の全カラムで
禁止訳語を FAIL にする（行番号・カラム・該当語・推奨原語を出す）。
`style` が無いと WARN が出る（検査は既定の正誤印だけになる）ので、雛形の `style` を有効にする。

出典を検査する（出典の欠落、front matter の `forbidden_sources` に挙げたホストの混入、
`source_scope` があればドメインのドキュメント領域外の出典）。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_sources.py" <folder>/quiz.csv --sections sections.md
```

`source_scope` はドメインごとに許可する URL 接頭辞の宣言で、範囲外は WARN（`severity: fail` で FAIL）。
**ホストが同じでも別製品のページを出典にした問題は、欠落・禁止ホスト・リンク切れのどの検査も通る**
（実績: ある講座で2件、精読レビューまで残った）。WARN は [[exam-validator]] の検証5で1問ずつ見分ける。

```yaml
source_scope:
  severity: warn                  # warn（既定）| fail
  include_primary_sources: true   # primary_sources の URL を全ドメイン共通で許可
  common: [docs.example.com/product-a/]
  domains:
    D4: [docs.example.com/identity/]
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
6. **出典の範囲と正答の食い違い** — `source_scope` 外の出典を、許可リストの漏れか別製品の出典かに見分け、出典と正答が食い違う疑いを報告

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_exam.py" --sections sections.md \
  --bank question-bank.md <folder>/quiz.csv
```

配分不足・重複・タイプ比率不足・distractor 無しが報告された場合は是正し、再実行するループを繰り返す（全クリーンまで）。

> **品質ゲートはシャッフル（Step 7）前に通すこと。** distractor 無し・タイプ比率不足は内容修正を伴うため、シャッフル後に発覚すると原本 `quiz.raw.csv` 修正＋再シャッフルの手戻りになる（実績あり）。Step 5 で必ず確定させる。

> **微小な外科的 CSV 修正はオーケストレータが直接行う。** distractor 化のために1選択肢を誤答へ書き換える・`Domain` セルを再タグするといった機械的修正は、サブエージェントに委譲せずオーケストレータが Python で直接編集してよい。サブエージェントは安全機構により「コーディネーター経由の承認」を受け付けず作業を拒否して停止することがある（実績あり）。判断不要の小修正で round-trip を増やさない。シャッフル後に直すときは次のいずれかにする。どれを選ぶかは `shuffle_options.py <folder>/quiz.csv --check-drift`（読むだけ）で原本との差分を見て決める。
> (a) `_parts/<ドメイン>.csv` を直して `finalize_section.py` を再実行する（推奨）
> (b) `quiz.csv` を直して `shuffle_options.py <folder>/quiz.csv --adopt`（手直しを正として原本を作り直してから混ぜ直す）
> (c) 原本 `quiz.raw.csv` を直して `shuffle_options.py <folder>/quiz.csv --force`（`quiz.csv` 側の差分を捨てて原本から混ぜ直す）
> [[review-section]] の修正は `quiz.csv` にだけ入っているので、混ぜ直すなら必ず (b)。

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

1. 原本 `<folder>/quiz.raw.csv` が無ければ退避する。原本とのずれ（raw ドリフト: 正解の入れ替えを
   含む、シャッフルでは説明できない差分）があれば**上書きせずに止まり**、`--adopt`（`quiz.csv` を正と
   する）/ `--force`（原本を正とする）の指定を求める。`finalize_section.py` は結合の直後なので
   `--adopt` で呼ぶ（手直しが消えないことは結合前の検査が保証する）
2. 常に**原本から**シャッフルする
3. シード1〜500を走査し、正解位置の最悪相対偏差が最小のシードを採用する
4. 位置ごとの実測票数と期待票数を表示する

**重要:**
- **`quiz.csv` を読んで `quiz.csv` に書き戻す旧方式は禁止。** 再ロール時に「一度混ぜた後」を再シャッフルしてしまい再現性が壊れる（再シャッフルの罠）
- 単一固定シードは使わない。**実績として seed=42 が正解を1位置に 78.8% 偏らせた**
- `quiz.raw.csv` は意図的に残す（再ロール用）。Step 9 のクリーンアップでも削除しない
- 偏りが残る場合は `--max-seed 2000` に広げる。それでもダメなら選択肢数のばらつきや正解選択肢の表現を見直す
- **`quiz.csv` を手直しした後に原本から再シャッフルすると、手直しが黙って消える。** `shuffle_options.py` は
  `quiz.csv` の内容が `quiz.raw.csv` のシャッフルでは説明できない（raw ドリフト。`Correct Answers`
  だけの修正も含む）と検知して止まる。止まったら、**手直しを残すなら `--adopt`**（`quiz.csv` から
  原本を作り直してから混ぜ直す）。**`--force` は原本を正として手直しを捨てる**ので、原本側を直した
  ときにだけ使う。混ぜ直す必要がなければ再シャッフルしない（[[review-section]] の修正後はこれが既定）。
  差分の確認だけなら `--check-drift`（何も書かない）

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

> **★ 最後の本を確定した直後に必ず回す。** 横断監査は全本が揃うまで
> 正解肢の類似を見られないので、**最終本の確定時が最初の検出機会**になる。
> 実績: ある講座では最終本の確定直後に **3 FAIL**（正解肢の類似 91% / 85% / 83%）が
> 出た。ここを飛ばすと公開後に直すことになる。
>
> 2本目以降は**確定するたびに回して**、差し戻しを1本分に閉じ込めるのが望ましい。

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
1. 問題数がそのセクションの目標問題数か（`mode: mixed` では `profile.py` の出力の該当行）
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
- 次ステップ: 他の模試も作成するか / 精読レビュー（[[review-section]]）に進むか / Udemy アップロードに進むか

### Step 12（任意）: 精読レビュー → 不変条件の検査

R3 承認後・アップロード前に、全問を1問ずつ読む精読レビューを行う（`/udemy-exam-prep:review-section <N|all>`）。
**機械検査をすべて通った講座でも、製品名の和訳・直訳調の日本語・別製品の出典は残る**
（実績: 全検査 OK の6本300問を精読して約400件見つかった）。出題言語と出典の言語が違う講座では実施を推奨する。

精読の指摘で `quiz.csv` を直したら、修正前（git HEAD または修正前のコピー）と比べて
正解・配分・選択肢数・出典・正誤印が動いていないことを検査する。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_invariants.py" <folder>/quiz.csv --sections sections.md
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_invariants.py" <folder>/quiz.csv --base <修正前のコピー>   # git 管理外
```

手順の詳細（精読エージェントへの指示テンプレート・A/B/C 分類・統一表記シート・要確認の扱い）は [[review-section]]。

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
- 精読レビュー（R3 後の任意工程）: [[review-section]]
- [[quiz-csv-format]] — CSV 規約
- [[research-cert-docs]] — 調査レシピ
