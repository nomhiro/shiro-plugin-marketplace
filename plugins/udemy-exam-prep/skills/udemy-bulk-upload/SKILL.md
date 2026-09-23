---
name: udemy-bulk-upload
description: Udemy 演習テストコースに quiz.csv を一括アップロード・編集するためのブラウザ操作レシピ（Claude in Chrome を第一手段、Playwright MCP を代替）。コース作成、テスト追加、設定値、CSV事前検証、公開中テストを編集画面ヘルパーで書き換える手順、既存テスト入れ替えのAPIワークアラウンドを含む。
---

# udemy-bulk-upload

Udemy 演習テストコースの作成・quiz.csv のアップロード・公開中テストの書き換えは、ブラウザ操作で自動化する。

## ブラウザ手段: Claude in Chrome を第一手段、Playwright は代替

| 手段 | 使うとき | 特徴 |
|---|---|---|
| **Claude in Chrome**（`mcp__claude-in-chrome__*`） | **第一手段** | ユーザーが普段使っている Chrome をそのまま操作する。**Udemy にログイン済みのセッションが使える** |
| Playwright MCP（`browser_*`） | Claude in Chrome が使えない環境 | 普段の Chrome とは**別プロファイル**のブラウザが起動する。毎回ユーザーにログインしてもらう必要があり、Chrome を閉じておく必要もある |

> 実績: 公開中コースの6本300問の書き換えで、ユーザーはログイン済みの Chrome を使える
> Claude in Chrome を求めた。Playwright はログインからやり直しになるため代替に回した。

主要操作の対応表（以下の手順は Playwright のツール名で書いてある箇所がある。Claude in Chrome ではこの表で読み替える）:

| 操作 | Claude in Chrome | Playwright MCP |
|---|---|---|
| タブの把握 | `tabs_context_mcp`（最初に必ず呼び、操作するタブ ID を決める） | `browser_tabs` |
| ページ移動 | `navigate` | `browser_navigate` |
| JS 実行 | `javascript_tool` | `browser_evaluate` / `browser_run_code_unsafe` |
| 要素を探す | `find`（自然文で探して ref を得る）/ `read_page`（アクセシビリティツリー） | `browser_snapshot` の ref / role / name |
| クリック・キー入力・スクリーンショット | `computer`（`left_click` は ref か座標、`type`、`screenshot`） | `browser_click` / `browser_type` / `browser_take_screenshot` |
| ファイル投入 | `file_upload`（`find` で得た `input[type="file"]` の **ref** とローカルの絶対パスを渡す） | `setInputFiles`（`browser_run_code_unsafe` 内） |

**`javascript_tool` の性質（実測）:**

- **トップレベル `await` が使える。** 関数で包まずに `await fetch(...)` と書ける
- **最後の式の値が返る。** `return` は書かない。オブジェクトは `JSON.stringify` して返すと読みやすい
- **1回の実行は45秒で CDP がタイムアウトする**（`Runtime.evaluate timed out after 45000ms`）。
  ページ側の処理は続くので、長い処理はバックグラウンドで起動し、状態を別の呼び出しで読む（`__u.runBg` / `__u.auditBg`）

どちらの手段でも、要素はアクセシビリティツリー由来の ref / role / name で取る（CSS セレクタは Udemy の動的構造では当たらないことが多い）。

## 前提条件

- Claude in Chrome 拡張が接続済み（`tabs_context_mcp` でタブが見える）。
  使えなければ Playwright MCP（`udemy-exam-prep` プラグインが `.mcp.json` で同梱している）
- Playwright を使う場合のみ: Chrome ブラウザが閉じている（Playwright 起動時の競合回避）
- 各セクションフォルダに quiz.csv が作成済み
- コースが**有料設定済み**（無料コースでは演習テストを追加できない仕様）

## Udemy 側の制約

| 制約 | 内容 |
|---|---|
| テスト数 | 演習テスト専用コースは**最大6テスト** |
| 無料コース | 演習テストを追加できない。先に有料設定にする |
| 公開済みテスト | 個別問題の削除・編集が API でできない（後述のワークアラウンド） |

## ステップ1: CSV 事前検証

アップロード前に必ず全 quiz.csv を検証する。FAIL があれば修正してからアップロードする。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_quiz_csv.py" section0*/quiz.csv
```

規約の詳細は [[quiz-csv-format]] を参照。

## ステップ2: ブラウザログイン

Claude in Chrome はユーザーの Chrome のセッションをそのまま使うので、通常ログインは不要。

```
Claude in Chrome:
1. tabs_context_mcp で操作するタブを決める（無ければ tabs_create_mcp で作る）
2. navigate https://www.udemy.com/instructor/courses/
3. ログイン画面に飛ばされたら、ユーザーにログインを依頼して応答を待つ
```

Playwright（別プロファイルなので毎回ログインが要る）:

```
1. browser_navigate https://www.udemy.com/join/login-popup/
2. ユーザーに「手動でログインしてください。2FA完了後に教えてください」と伝える
3. ユーザー応答を待つ
4. browser_snapshot でログイン状態を確認
```

**資格情報を自分で入力してはいけない。** ログインが必要な状態に当たったら、そこで停止してユーザーに依頼する。

## ステップ3: コース管理ページへ移動

```
1. browser_navigate https://www.udemy.com/instructor/courses/
2. browser_snapshot で該当コースのリンクを探す
3. クリックしてコース管理ページに入る
```

## ステップ4: 演習テストの追加（最大6本）

**3つの名前を混同しないこと**（実測の正確な名前）。

```
1. カリキュラム編集ページで button "カリキュラム項目を追加" をクリック
2. ドロップダウンの button "演習テスト 認定資格準備の時間制限付き試験" を選ぶ
3. textbox "タイトル（60文字以内）" に入力
   （sections.md のセクション名のみ。「セクションN:」プレフィックスは含めない）
4. 送信は button "演習テストを追加"（「追加」ではない）
5. 2つ目以降は、直前のテスト下部の "カリキュラム項目を追加" から同じ手順
```

**6本を先にまとめて作り、あとで1本ずつ設定と投入をするのが速い。**
作成のたびに返る `編集` リンクの `quizId` を記録しておく。

### 「編集」と「削除」は隣接している

テスト行には `img "編集"` を持つ **link** と `img "削除"` を持つ **button** が並ぶ。
ref を1つ取り違えると削除に当たる。

> 実績: 編集だと思った ref が削除で、`カリキュラム項目を削除しようとしています。
> よろしいですか？` のダイアログが出た。**`キャンセル` を押せば無傷で戻れる**が、
> `OK` を押すと 60 問ごと消える。**クリック前に snapshot の `img` の名前で
> link / button のどちらかを確かめる。**

## ステップ5: 各テストの設定

各演習テストの編集ページで設定する。URL は次の形。

```
https://www.udemy.com/course/<courseId>/manage/practice-test/?quizId=<quizId>
```

**`/instructor` を付けてはいけない。** 付けると `/instructor/course/<id>/manage/404`
にリダイレクトされる（カリキュラムページの方は `/instructor` 付きなので紛れやすい）。
カリキュラムの `編集` リンクの `/url` はこの相対パスで出る。

| 項目 | 値 |
|------|--------|
| 時間（分） | `sections.md` front matter の `exam.minutes` をそのまま（本番と同条件）。`exam.minutes` が無い資格では `問題数 × 1.5` を使う |
| 合格最低点（%） | 70 |
| 質問と回答の順序をランダム化 | **ON**（必須） |

**Playwright の注意点:**

- 欄は**構造で取る**のが確実。`input[type="number"]` の **nth(0)=時間 / nth(1)=合格点**
  （アクセシビリティ名は再描画で落ちる）
- 「質問と回答の順序をランダム化」の `input[type="checkbox"]` は `ud-sr-only` で隠れており、
  `label[class*="ud-switch-container"]` が pointer events を遮る。
  **input の `id` を読んで `label[for="<id>"]` を押す:**

  ```js
  const cb = page.locator('input[type="checkbox"]').first();
  const id = await cb.getAttribute('id');          // 実測: "switch--43"（ページ毎に変わる）
  if (!(await cb.isChecked())) await page.locator(`label[for="${id}"]`).click();
  ```

  > 「親の generic 要素をクリック」は**当たるページと当たらないページがある。**
  > 実績: 1本目は親 generic で成功したが、2本目は同じ手順で
  > `label[class*="ud-switch-container"] intercepts pointer events` で失敗した。
  > `label[for=<id>]` は6本すべてで成功した。

- 設定変更後は必ず「保存」ボタンを `browser_click`
- **保存しても成功の根拠にしない。** リロードして `spinbutton` の値と
  `checkbox ... [checked]` を読み直す

## ステップ6: CSV 一括アップロード

**「CSVファイルのアップロード」ボタンは押さない。**
押すとネイティブのファイル選択ダイアログが滞留し、他のツールが
`does not handle the modal state` で全滅する。ダイアログを開かせる代わりに、
**モーダル内に既に存在する `input[type="file"]` へ直接渡す。**

Claude in Chrome:

```
1. 「質問を追加」→「一括アップロード」をクリック（computer の left_click か find で得た ref）
2. find で「CSV のファイル入力（input[type=file]）」を探して ref を得る
3. file_upload にその ref と <abs>/quiz.csv を渡す
4. find / screenshot で「問題が作成されます。」を確かめてから「閉じる」を押す
```

Playwright:

```js
async () => {
  await page.getByRole('button', { name: '質問を追加' }).click();
  await page.getByRole('button', { name: '一括アップロード' }).click();
  await page.waitForSelector('input[type="file"]', { state: 'attached' });
  await page.locator('input[type="file"]').setInputFiles('<abs>/quiz.csv');
  await page.getByText('問題が作成されます。').first()
            .waitFor({ state: 'visible', timeout: 60000 });
  await page.getByRole('button', { name: '閉じる', exact: true }).click();
}
```

実測した細部:

| 項目 | 実測 |
|---|---|
| `input[type="file"]` | モーダル内に **`accept="text/csv"` のものが1つだけ**。曖昧にならない |
| 待つテキスト | **「問題が作成されます。」**（「アップロード完了」ではない）。`成功アラート` のラベルが付いた dialog に出る |
| 閉じるボタン | **`exact: true` が必須。** 付けないと `img "モーダルダイアログを閉じる"` にも部分一致して strict mode violation になる |
| 所要時間 | 60問で10秒前後 |
| テンプレート版 | ダイアログのリンクは `PracticeTestBulkQuestionUploadTemplate_V2.2.csv`。ヘッダー17列は v2 と完全一致 |

### `browser_run_code_unsafe` は `async () => { ... }` で渡す

**トップレベルの文を受け付けない。** `const x = ...` や `await page...` から
始めると `SyntaxError: Unexpected token 'const'` / `Unexpected identifier 'page'`
になる。上のように**アロー関数1つ**として渡す。`setInputFiles` を使う以上
必ず通る道なので、最初からこの形で書く。

## 既存テストの問題を入れ替える場合

**重要:** Udemy API は**公開済みテストの個別問題の削除・編集ができない**。`is_draft: true` や `is_published: false` を PATCH しても、問題操作 API は400を返す。

### まず「何問直すのか」で分ける

| 直す範囲 | 手順 |
|---|---|
| **1〜数問の一部（選択肢の文面・解説・ドメイン）** | **UI で直接編集する。削除は不要** |
| **多数の問題の書き換え**（全問の解説の整形・記号の一括除去など） | **UI で問題ごとに書き換える。ヘルパーで自動化する（下記「多数の問題を書き換える」）** |
| テストの構成そのものの作り直し | テスト自体を削除→再作成（下記。**最終手段**。受講者の受験結果が失われる可能性がある。**公開済みのコースでは行わない**） |

**API が編集できないのは API 経由の話で、UI の問題エディタは編集できる。**
削除→再作成は 60 問すべてを作り直すことになるので、部分修正には使わない。

```
1. 問題一覧の tab "N. 問題文…" をクリックして当該問題を開く
2. リッチテキスト欄を fill する
   - 選択肢:     textbox "回答を追加" の nth(k)
   - 選択肢の解説: textbox "学習者に回答を説明" の nth(k)
   - 全体解説:   最後の textbox "学習者に回答を説明"
3. button "質問を保存" をクリック
   ★ 演習テスト設定の button "保存" とは別のボタン。混同すると保存されない
4. リロードして innerText を読み直して反映を確認する
```

> 実績: 投入後に1問の選択肢1つだけを直す必要が出た。削除→再作成なら 60 問の
> 再投入だが、UI 編集なら2つの欄と1クリックで済み、他の 59 問に触らずに終わった。
> CSV 側（Source of Truth）も同じ内容に直してから検証スクリプトを通し直すこと。

### 多数の問題を書き換える（ヘルパー）

テストを削除せず、問題の並びや設定を残したまま、編集画面で問題ごとに書き換える。Claude in Chrome の `javascript_tool`（代替は Playwright の `browser_evaluate`）で、ログイン済みの編集画面 `https://www.udemy.com/course/<courseId>/manage/practice-test/?quizId=<id>` を使う。**公開済み（ライブ）のコースでは、受講者の受験結果を失わないよう、この方法を使う**（テストの削除→再作成はしない）。

#### 始める前に守ること

- **1本ずつ・1タブで進める。並行実行は逆効果。**
  > 実績: 6本を6タブで同時に `runBg` したところ、各タブが数問ずつしか進まず `align` の abort が多発した。1タブで1本ずつに戻すと安定した。
- **タブを前面に出しておく。** 裏に回ったタブ（`document.visibilityState === 'hidden'`）はブラウザがタイマーを絞るので、ヘルパーの待ち時間が伸びて照合が止まる。開始前と長い処理の途中で `__u.visible()` を読み、`'hidden'` ならユーザーに「Udemy の編集画面のタブを前面に表示してください」と依頼し、戻るまで進めない。`runBg` / `auditBg` 中に hidden になると、`jobStatus()` / `auditStatus()` の `hidden` に問題番号と時刻が残る
  > 実績: タブが裏に回ったまま照合が進まなくなった。前面に戻すと再開した。
- **ページを再読み込みすると `__u`・データ・ジョブ状態は消える。** 再読み込みの前に `__u.jobStatus()` でどこまで進んだかを控え、再読み込み後はヘルパーの読み込みと `__u.load(<セクション番号>)` からやり直す（同期サーバーは起動したままにしておく）

#### 手順

1. 同期サーバーをバックグラウンドで起動する（`quiz.csv` から問題データと署名を配る。127.0.0.1 のみ）
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/udemy_sync_server.py" <project_root> --old-ref <Udemy に載っている版のコミット>`
2. 編集画面でヘルパーを読み込み、タブの可視性を確かめる
   `eval(await (await fetch('http://127.0.0.1:8765/editor-helper.js')).text()); [await __u.load(<セクション番号>), __u.visible()]`
3. **照合処理の自己検証（推奨）**: **CSV の行が `--old-ref` の版から実際に変わっている問題**を1問選び、書き換える前に `await __u.audit(q, q)` で照合して、**不一致が返る**ことを確かめる。変わっていない問題では空配列が正しい結果なので、この確認に使わない。変わっている問題で空配列が返るなら照合が何も検出できていない（データのセクション番号違い・旧版の取り違えなど）ので、先に原因を直す
4. `__u.fast = true; __u.runBg([問題番号, ...])` で起動し、`__u.jobStatus()` で進捗を見る。1問ごとに、位置合わせ → 入力 → 署名照合 → 保存まで自動で行う
   - **1問につき最大 `__u.tries`（既定3）回試行する。** 失敗（`abort` / `ok:false` / 例外）したら「更新が保存されていません」モーダルを `dismiss()` で閉じ、`fast` を切った通常モード（保存後に別の問題へ移って戻り再照合する）で同じ問題をやり直す。再試行の間は `__u.retryWait`（既定2.5秒）待つ。`fast` の設定はジョブ終了時に元へ戻る
   - 3回とも失敗すると `stopped` にその問題の結果が入って止まる。`jobStatus()` の `retries`（再試行回数）と `log`（失敗した試行の直近5件）で原因を見る
   - 途中で止めたいときは `__u.stop()`。実行中の問題を終えたところで止まり、`stopped` は `{abort:'stop', q:<次の問題>}` になる
   - `runAll`（同期版）は使わない。通常モードでは1問でも45秒を超えたことがある
5. 全問が終わったら（`jobStatus()` が `running:false`。保存の途中で再読み込みしない）**ページを再読み込みし、ヘルパーの読み込みと `__u.load(<セクション番号>)` をやり直してから** `__u.auditBg(1, <問題数>)` で照合し、`__u.auditStatus()` を読む。`at` が進捗、`mismatch` が CSV と食い違う問題、`err` が照合中に例外が出た問題。`done: true` かつ `mismatch` と `err` が空なら、サーバーに保存された内容が CSV と完全一致
   > 実績: 同期版の `audit` を50問に掛けると45秒を超え、途中の例外で完了フラグが立たないまま止まった。`auditBg` は1問ずつ例外を捕まえて最後まで進む。同期版は 15 問程度までに留める。
6. `mismatch` / `err` の問題だけ `runBg` でやり直し、もう一度 `auditBg` する
7. 次の本へ進む（同じタブで編集画面を移動し、手順2から）。全本が終わったら公開する（下記）

#### 「保存して移行」がスピナーのまま固まったとき

「更新が保存されていません」モーダルは通常 `dismiss()`（×ボタン）で閉じられる。閉じられず、**「保存して移行」を押すとスピナーが回ったまま戻らない**ことがある。

> 実績: 公開中コースの一括書き換え中に1回発生した。`dismiss()` では閉じられなかった。

回復手順:

1. `__u.jobStatus()` で止まった問題番号を控える（ジョブが動いていれば `__u.stop()`）
2. モーダルの「**保存せずに離れる**」を押す
3. ページを再読み込みし、ヘルパーを読み込み直して `__u.load(<セクション番号>)`
4. 止まった問題を `__u.fast = false; __u.runBg([q])` で再実行する。`fast` は起動時の値（false）に戻るので、残りを速く進めるなら `__u.fast = true` にしてから `runBg` で続ける
5. 最後に `auditBg` で全問を照合する（固まった問題の保存有無は画面からは判断できないため）

**注意点（実績）:**

- 入力は `execCommand('insertText')`。キー入力（`computer` の `type`、`browser_type` など）は、文字の欠落・置換・入れ替わりが起きた（キャレットが再描画で飛ぶ）ので使わない。実改行は段落（`<p>`）として保存され、空行は空の段落になる
- 問題の切り替えは `click()` では動かない。`pointerdown → mousedown → pointerup → mouseup → click` の順にイベントを送る（ヘルパーが実装済み）
- **問題タイプの変更（選択式 ↔ 複数選択）は自動化の対象外。** `__u.setType('複数選択')` → 選択肢の追加 → 入力 → ドメイン選択のあと、**実際のマウスクリック**（`computer` の `left_click`）で「質問を保存」を押す。JS の `.click()` では保存が黙って失敗し、二重登録になったことがある（問題数が50→52）。二重登録が出たら、重複した問題を実マウスで「削除」する
- クリックする座標はスクリーンショットで確認する。JS の `getBoundingClientRect` の値とは縮尺が違う
- 選択肢数を増やす修正は `run` が自動で行う（減らす修正は手動）

ヘルパーの API（`udemy_editor_helper.js`）:

| 関数 | 用途 |
|---|---|
| `load(sec)` | 問題データと旧版の署名を取得 |
| `visible()` | `document.visibilityState` を返す。`'hidden'` なら前面表示を依頼する |
| `runBg(list)` / `jobStatus()` | バックグラウンドで書き換え（再試行内蔵）/ 進捗・`retries`・`log`・`hidden`・`stopped` |
| `stop()` | 実行中の `runBg` / `auditBg` を次の問題の手前で止める |
| `auditBg(a, b)` / `auditStatus()` | バックグラウンドで照合 / `at`・`mismatch`・`err`・`hidden`・`done` |
| `audit(a, b)` | 同期版の照合（15問程度まで） |
| `dismiss()` | 「更新が保存されていません」モーダルを×で閉じる |

### 公開（変更内容を公開）

**公開してよいかは、プロジェクトの `CLAUDE.md` の公開方針に従う。** 記載がなければ公開ボタンは押さず、ユーザーの許可を得てから行う（公開は受講者に見える操作）。

1. 右上の「変更内容を公開」をクリックする
2. **ダイアログが開いたことを確かめてから入力する。** `find` かスクリーンショットで「**学習者に更新メッセージを送信**」の文言が出ていることを確認し、メッセージ欄の ref を取ってから入力する
   > 実績: クリック直後に入力したところ、ダイアログが開く前に文字が打ち込まれた。このときは無害だったが、編集中の欄に入れば問題文を壊す。
3. メッセージは必須で、既存の受講生の結果ページに表示される。**事実だけを簡潔に書く。** 正解が変わっていなければその旨を書く（例: 「製品名の表記と解説の日本語表現を修正しました。正解に変更はありません。」）。**正解を変えた問題があるなら、そのことを書く**（「変更はない」と書かない）
4. 「指導目的のお知らせとして送信」は受講生へのメール通知になる（月4回まで）。**オフのまま**にする
5. 送信後、「演習テストが公開されました！」が出るまで最大20秒ほどかかる。ダイアログが残っていても、再クリックせずに待つ
6. 公開の結果は `udemy-course-meta.md` の更新履歴に残す（[[upload-practice-tests]]「更新履歴を残す」）

### テスト自体を削除→再作成する手順

`browser_evaluate` 経由で以下を実行する。

```javascript
const csrfToken = document.cookie
  .split(';')
  .find(c => c.trim().startsWith('csrftoken='))
  .split('=')[1];

const headers = {
  'X-CSRFToken': csrfToken,
  'Content-Type': 'application/json',
};

// 非公開にしてからテスト本体を削除
await fetch(`/api-2.0/courses/${courseId}/quizzes/${quizId}/`, {
  method: 'PATCH',
  headers,
  body: JSON.stringify({ is_published: false }),
});
await fetch(`/api-2.0/courses/${courseId}/quizzes/${quizId}/`, {
  method: 'DELETE',
  headers,
});
```

**ポイント:**
- API DELETE 後もカリキュラムページにテスト枠が残ることがある → UI の「削除」ボタンで確実に消す
- テスト削除はバックグラウンド処理。直後に新規テスト作成するとカウントエラーが出る場合がある（数秒待ってリトライ）

その後、ステップ4〜6 で再作成する。

### テストタイトルだけ変更（削除不要）

```javascript
await fetch(`/api-2.0/courses/${courseId}/quizzes/${quizId}/`, {
  method: 'PATCH',
  headers: {
    'X-CSRFToken': csrfToken,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ title: '新しいタイトル' }),
});
```

## エラーハンドリング

| 症状 | 原因 | 対処 |
|------|------|------|
| CSV アップロード後「ヘッダーが正しくありません」 | BOM 混入 | `utf-8`（BOM 無し）で書き直し。`write_rows` を使う |
| アップロード後「行Nがフォーマット不正」 | 17カラム不一致 | `validate_quiz_csv.py` を再実行 |
| multi-select 取り込み失敗 | 正解が1個しかない | `multiple-choice` に変更 |
| 演習テストを追加できない | コースが無料設定 | 先に有料設定にする |
| 7本目を追加できない | 演習テストは最大6本 | 仕様。本数を6以下にする |
| ファイル選択ダイアログが開かない | Modal state が違う | `browser_snapshot` で状態確認、UI操作からやり直し |
| クリックできない要素 | `ud-sr-only` の input がラベルに遮られている | input の `id` を読んで `label[for="<id>"]` を押す（親 generic は当たらないページがある） |
| `does not handle the modal state` で全ツールが失敗 | ファイル選択ダイアログが滞留している | ページを再ナビゲートして解消する。以後はボタンを押さず `setInputFiles` を使う |
| `Ref ... not found` | 保存や再描画で ref が採番し直された | snapshot を取り直す。設定欄は `input[type="number"]` の nth で取る |
| 「更新が保存されていません」モーダルが出る | 保存に失敗している（特にタイプ変更後） | 実マウスで「質問を保存」を押し直す。内容が戻っていたら入力からやり直す |
| CDP が `Runtime.evaluate timed out after 45000ms` | 1回の JS 実行が45秒を超えた | `runBg` / `auditBg` で起動し、`jobStatus()` / `auditStatus()` を別の呼び出しで読む。ページ側の処理は続く |
| `runBg` / `auditBg` が進まない・`align` の abort が続く | タブが裏に回っている（`visibilityState` が `hidden`）/ 複数タブで並行実行している | `__u.visible()` と `hidden` の記録を見る。ユーザーにタブの前面表示を依頼し、1タブ1本に絞る |
| 「保存して移行」がスピナーのまま戻らない | 保存処理が固まった | 「保存せずに離れる」→ 再読み込み → その問題を `fast = false` で再実行 → `auditBg`（「多数の問題を書き換える」参照） |
| 公開ダイアログの外に文字が入った | 「変更内容を公開」の直後、ダイアログが開く前に入力した | 「学習者に更新メッセージを送信」の文言を確かめてから入力する |
| 公開ダイアログの「変更を送信して公開」が押せない | 更新メッセージが空 | メッセージを入力する（必須） |
| 投入後に選択肢の一部が消えている | `<単語>` 形がサニタイザで削除された | `validate_quiz_csv.py` を通す（タグ検査が FAIL にする）。[[quiz-csv-format]] 厳守ルール9 |

## ペアになるスキル

- アップロード前の CSV 品質は [[quiz-csv-format]] で保証
- セクション横断のオーケストレーションは [[upload-practice-tests]]
- 受講者の指摘を受けた修正全体の流れは [[handle-student-feedback]]
