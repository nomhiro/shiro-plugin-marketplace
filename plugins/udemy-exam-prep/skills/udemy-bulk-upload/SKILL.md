---
name: udemy-bulk-upload
description: Udemy 演習テストコースに quiz.csv を一括アップロードするためのPlaywright操作レシピ。コース作成、テスト追加、設定値、CSV事前検証、既存テスト入れ替えのAPIワークアラウンドを含む。
---

# udemy-bulk-upload

Udemy 演習テストコースの作成と quiz.csv アップロードは、Playwright MCP（`@playwright/mcp`）で自動化する。アクセシビリティツリーベースで動作するため、`browser_snapshot` で取得した ref / role / name を使う（CSS セレクタは使わない）。

## 前提条件

- Playwright MCP が利用可能（`udemy-exam-prep` プラグインが `.mcp.json` で同梱している）
- Chrome ブラウザが閉じている（Playwright 起動時の競合回避）
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
**モーダル内に既に存在する `input[type="file"]` へ `setInputFiles` で直接渡す。**

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
| テストの構成そのものの作り直し | テスト自体を削除→再作成（下記。**最終手段**。受講者の受験結果が失われる可能性がある） |

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

テストを削除せず、問題の並びや設定を残したまま、編集画面で問題ごとに書き換える。Claude in Chrome（または Playwright の `browser_evaluate`）で、ログイン済みの編集画面 `https://www.udemy.com/course/<courseId>/manage/practice-test/?quizId=<id>` を使う。

1. 同期サーバーをバックグラウンドで起動する（`quiz.csv` から問題データと署名を配る。127.0.0.1 のみ）
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/udemy_sync_server.py" <project_root> --old-ref <Udemy に載っている版のコミット>`
2. 編集画面でヘルパーを読み込む
   `eval(await (await fetch('http://127.0.0.1:8765/editor-helper.js')).text()); await __u.load(<セクション番号>)`
3. 少数なら `await __u.runAll([問題番号, ...])` を **4問ずつ**（1問あたり約8〜20秒。CDP は45秒でタイムアウトする）。多数なら `__u.fast = true; __u.runBg([問題番号, ...])` で起動し、`__u.jobStatus()` で進捗を見る。1問ごとに、位置合わせ → 入力 → 署名照合 → 保存まで自動で行う（`fast` を使わないと、保存後に別の問題へ移って戻り再照合する）。`abort` が返ったら止めて原因を見る。**`fast` は保存待ちが短く、まれに「更新が保存されていません」のモーダルが出て `align` で停止する**（実績: 250問中1回）。モーダルを閉じて `fast` を切り、止まった問題から再実行する。`fast` で反映した分も、最後の `audit` で必ず全問を照合する
4. 全問が終わったら**ページを再読み込みしてから** `await __u.audit(1, 17)` のように 15〜20 問ずつ照合する。空配列なら CSV と完全一致（サーバーに保存された内容を見ている）
5. 公開する（下記）

**注意点（実績）:**

- 入力は `execCommand('insertText')`。キー入力（`browser_type` など）は、文字の欠落・置換・入れ替わりが起きた（キャレットが再描画で飛ぶ）ので使わない。実改行は段落（`<p>`）として保存され、空行は空の段落になる
- 問題の切り替えは `click()` では動かない。`pointerdown → mousedown → pointerup → mouseup → click` の順にイベントを送る（ヘルパーが実装済み）
- **問題タイプの変更（選択式 ↔ 複数選択）は自動化の対象外。** `__u.setType('複数選択')` → 選択肢の追加 → 入力 → ドメイン選択のあと、**実際のマウスクリック**で「質問を保存」を押す。JS の `.click()` では保存が黙って失敗し、二重登録になったことがある（問題数が50→52）。二重登録が出たら、重複した問題を実マウスで「削除」する
- クリックする座標はスクリーンショットで確認する。JS の `getBoundingClientRect` の値とは縮尺が違う
- 選択肢数を増やす修正は `run` が自動で行う（減らす修正は手動）

### 公開（変更内容を公開）

- 右上の「変更内容を公開」を押すと、**「学習者に更新メッセージを送信」ダイアログ**が出る。メッセージは必須で、既存の受講生の結果ページに表示される。事実だけを簡潔に書く（例: 「解説の表示を修正しました。問題・解答の内容に変更はありません」）
- 「指導目的のお知らせとして送信」は受講生へのメール通知になる（月4回まで）。**オフのまま**にする
- 送信後、「演習テストが公開されました！」が出るまで最大20秒ほどかかる。ダイアログが残っていても、再クリックせずに待つ
- 公開は受講者に見える操作。ユーザーの許可を得てから行う

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
| CDP が `Runtime.evaluate timed out after 45000ms` | 1回の JS 実行が45秒を超えた | `runBg` を使うか 4 問ずつに分ける。ページ側の処理は続くので、待ってから `audit` で確認 |
| 公開ダイアログの「変更を送信して公開」が押せない | 更新メッセージが空 | メッセージを入力する（必須） |
| 投入後に選択肢の一部が消えている | `<単語>` 形がサニタイザで削除された | `validate_quiz_csv.py` を通す（タグ検査が FAIL にする）。[[quiz-csv-format]] 厳守ルール9 |

## ペアになるスキル

- アップロード前の CSV 品質は [[quiz-csv-format]] で保証
- セクション横断のオーケストレーションは [[upload-practice-tests]]
- 受講者の指摘を受けた修正全体の流れは [[handle-student-feedback]]
