---
name: publish-video-course
description: 完成した講座動画（mp4）を Udemy の動画講座に載せる。コースの枠（基本情報・価格・メッセージ）、セクションと講義の並び、動画のアップロード（10MB を超えるファイルをページ内スクリプトで選ぶ）、小テスト（Udemy のクイズ＝simple-quiz）の入力、題名の改名と検証、差し替えまでをブラウザ操作（Claude in Chrome）と Udemy の内部 API で行う。公開・審査への提出はしない。「Udemy に動画講座を作って」「動画をアップロードして」「小テストを Udemy に入れて」「講義の動画を差し替えて」で起動。
allowed-tools: Read, Write, Glob, Grep, Bash
---

# publish-video-course

完成した講座動画を Udemy の**動画講座**に載せるスキル。演習テスト講座（CSV の一括アップロードがある）は
`udemy-exam-prep` の `create-udemy-course` / `udemy-bulk-upload` が担当する。コースの基本情報の入力
（長文の入れ方・コース画像・規約上の注意・API で保存できる項目）は `create-udemy-course` と同じなので、そちらを読む。
このスキルは**動画講座に固有の部分**だけを持つ。

実績：座学 241 本・約 19 時間・12 セクションの講座で、枠の作成から動画のアップロード（失敗 0）、
小テスト 51 本・158 問の入力までをこの手順で行った。

## 🔴 してはいけないこと

- **公開・審査への提出はしない。** 制作者が内容を確かめて自分で押す
- 価格・クーポン・プロモーションの設定は、制作者の指示があるときだけ
- **ログイン中の Chrome のタブを閉じない・別のページへ移動しない**（アップロード中に移動すると止まる）
- ファイルサーバーは **127.0.0.1 にだけ** bind する。置き場の外を配らない。使い終わったら PID を指定して止める

## 流れ

1. **カリキュラムを作る**（講座側）：セクション＝章、講義＝動画1本、小テストの位置、の並びを JSON にする
2. **コースの枠**：`create-udemy-course` の手順で基本情報・学習目標・前提・対象者・メッセージ・価格を入れる
3. **セクションと講義**を API で作り、並びを PUT で決め、GET で突き合わせる
4. **動画**をアップロードする（ファイルサーバー＋ページ内スクリプト）
5. **講義名を改名**する（番号を外す。アップロードが終わった講義から順に）
6. **小テスト**を入れて並びに挿す
7. **検証**：講義数・動画の付いた講義数・小テストの問題数・並びを、原稿と全数で突き合わせる
8. 状態を講座側の一覧（`upload_state.json` など）に残し、制作者に報告する（公開は制作者）

## 1. カリキュラム（講座側）

- 制作の一覧表から作る。区切りだけの短い動画（間の札など）は講義にしない
- **講義名に番号を入れない**（制作者の指示。制作中のファイル名・一覧は番号つきでよい）。
  「1-2-3 〇〇」→「〇〇」。章の全体像のような番号だけで区別していた題名は「全体像：<章名>」のように中身の名前にする。
  題名は 80 字以内
- 組（まとまり）の名前は、**設計書ではなく動画の中身**に合わせる。設計書と動画がずれていた例がある
  （設計書の「プライバシー」の組の実体が「公平性」だった）。補正表を講座側に持つ
- アップロード用に、セクションごとのフォルダ（`00`, `01`, …）へ、講義の順に並ぶ名前（`001_<講義名>.mp4`）で
  **ハードリンク**を置く（容量を食わない）

## 2. API の呼び方（ページ内）

Claude in Chrome の `javascript_tool` で、ログイン済みの管理画面
（`https://www.udemy.com/instructor/course/<courseId>/manage/curriculum/`）から呼ぶ。

```js
const csrf = document.cookie.split('; ').find(c => c.startsWith('csrftoken=')).split('=')[1];
window.__api = async (m, p, b) => {
  const r = await fetch(p, {method: m, credentials: 'include',
    headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'application/json'},
    body: b ? JSON.stringify(b) : undefined});
  let j = null; try { j = await r.json(); } catch (e) {}
  return {s: r.status, j};
};
```

- **ページを移動すると `window.__*` は消える。** 移動したら定義し直す。長い処理の進み具合はページの外
  （127.0.0.1 の小さな受け口に POST するなど）にも書く
- **1回の評価は約 45 秒で切れる。** 長いループは `window.__go()` のように投げっぱなしにし、状態を短い呼び出しで読む
- 結果を返すときは、Cookie やクエリ文字列を含めない（ツールの出力で塞がれる）。メソッド・パス・状態だけ返す

| 操作 | API |
|---|---|
| セクションを作る | `POST /api-2.0/users/me/taught-courses/<courseId>/chapters/` `{title}` |
| 講義を作る | `POST /api-2.0/users/me/taught-courses/<courseId>/lectures/` `{title}` |
| 題名を変える | `PATCH /api-2.0/users/me/taught-courses/<courseId>/chapters|lectures/<id>/` `{title}` |
| 並びを決める | `PUT /api-2.0/courses/<courseId>/instructor-curriculum-items/` 本文 `{"items": "<JSON 文字列>"}`。中身は `[{id, class: "chapter"|"lecture"|"quiz", is_published: true}]`（クイズは `type: "simple-quiz"` も付ける） |
| 並びを読む | `GET /api-2.0/courses/<courseId>/instructor-curriculum-items/?page_size=400&fields[chapter]=title&fields[lecture]=title,asset&fields[quiz]=title` |
| クイズを作る | `POST /api-2.0/courses/<courseId>/quizzes/` `{title, description, type: "simple-quiz"}` |
| 問題を入れる | `POST /api-2.0/quizzes/<quizId>/assessments/`（本文は `scripts/udemy_quiz_payload.py` が作る） |
| 問題を上書きする | `PUT /api-2.0/quizzes/<quizId>/assessments/<id>/` |

`items` は**配列を JSON 文字列にしたもの**を値に入れる（配列のままでは通らない）。

## 3. 動画のアップロード

**Claude in Chrome の `file_upload` は合計 10MB が上限**で、講義の動画（20MB 前後）は通らない。
代わりに、ページ内で「ファイルを選んだ」操作を再現して、Udemy 自身のアップローダを動かす。

1. 置き場を配る：`python scripts/udemy_file_server.py <置き場>`（127.0.0.1:8765。CORS と Private Network Access のヘッダ付き。
   https のページから読めることを実測で確かめた）
2. 講義の行ごとに、ページ内でこうする：

```js
// row = [data-purpose="lecture-editor"] のうち、題名（[data-purpose="item-full-title"]）が一致する行
row.querySelector('[data-purpose="lecture-add-content-btn"]').click();      // ＋コンテンツ
(await waitFor(() => row.querySelector('[data-purpose="select-video"]'))).click();   // ビデオ
const inp = await waitFor(() => row.querySelector('input[type="file"]'));
const b = await (await fetch(`http://127.0.0.1:8765/f/${nn}/${k}`)).blob();
const dt = new DataTransfer();
dt.items.add(new File([b], `${title}.mp4`, {type: 'video/mp4'}));
inp.files = dt.files;
inp.dispatchEvent(new Event('change', {bubbles: true}));
// 行の文字が「処理」「完了」「プレビュー」などに変わるまで待つ。「エラー」「失敗」なら失敗に数える
```

- 題名の一致は、行の表示の頭に付く「レクチャー N:」を外してから比べる
- 既にコンテンツのある行（＋コンテンツのボタンが無い行）は飛ばす（やり直しで二重に付けない）
- 終わった行は折りたたむ（`lecture-collapse-btn`）。開いたままにするとページが重くなる
- **速さは回線で決まる。** 実測で約 2 本/分、同時 2 本でも 4 本でも変わらなかった。同時 2 本で十分
- 進み具合は Monitor（ローカルの進捗ファイルを読む小さな poller）で待つ。sleep で待たない
- Udemy 側のエンコードは非同期。アップロードが終わっても、asset の状態がしばらく処理中のまま
- **改名はアップロード完了を待たず、終わった講義から順に行う。** 全部が終わるまで番号つきの題名が見えたままになり、
  制作者に指摘された

## 4. 小テスト（Udemy のクイズ）

演習テストとは別物。CSV の一括アップロードは無いので、1問ずつ API で入れる。

1. 講座側で原稿を読み、`[{slug, title, description, questions: [{id, question, options, correct, explanation}]}]` の JSON にする
   - **原稿の「問題」の節だけを読む。** 後ろの「保留案」「参照」の節まで読むと、同じ番号の問題が重複して入る
   - 正解の印は括弧つきの書き方（「正解（不適切）」など）もある。印の読み取りは括弧を許す
   - 検証：選択肢 2〜6・正解はちょうど1つ・解説がある。外れた問題は入れずに報告する
2. `python scripts/udemy_quiz_payload.py quizzes.json -o quiz_import.json` で、API に送る本文を作る
   - `**太字**` を外す（クイズでは記号のまま出る）。`- ` の行は箇条書きになる
   - 選択肢ごとの解説は「正解です。」／「不正解です。」＋解説全文（どれを選んでも理由が読める）
   - 正解の位置の偏り（a..f の数）を表示する。偏りが大きければ原稿で入れ替える
3. ページ内で、クイズを作り（`POST …/quizzes/`）、問題を順に入れる（`POST …/assessments/`）。
   入れた問題の id を記録して、やり直しで二重に入れない
4. 並び（`PUT …/instructor-curriculum-items/`）で、各まとまりの最後の講義の次に挿す
5. 題名は「<主題>：確認テスト」のように番号なしにする

**問題の DELETE は 204 を返しても消えないことがある。** 試しに入れた問題は、消さずに本物の問題で PUT して上書きする。

## 5. 検証（全数）

- 並び：GET した並び（セクション・講義・クイズ）を、講座側の JSON と1件ずつ突き合わせる（件数だけで済ませない）
- 動画：全講義に asset が付いているか。処理中の数も報告する
- 小テスト：クイズごとの問題数が原稿と一致するか。1本は画面で開き、箇条書きや改行が崩れていないかを見る
- 説明欄などの長文は、入力後の innerText を原稿と突き合わせる（原稿に無い語が紛れていた例がある）

## 6. 審査で求められたこと

- **AI を使った講座は、説明文の先頭に「本コースにはAIの使用が含まれています。」を入れる**（審査で求められた。文言は変えない）。
  台本・図解・音声に AI を使う講座は、最初から入れておく。続けて「■ AI の使用について」として、
  企画と確認は講師、台本と図解は AI の支援、ナレーションは合成音声、のように役割を書いておくとよい
- 説明欄はリッチテキスト（ProseMirror）。**箇条書きはツールバーのリストボタンで作る**（「・」を打っても箇条書きにならない）

## 7. 差し替え（公開後）

- 動画を直したら、その講義のコンテンツを置き換える（講義を消して作り直さない。受講者の進み具合が消える）
- 小テストの問題は PUT で上書きする
- **公開後の変更は制作者の指示があるときだけ行う**

## 関連

- 上流：`make-lecture-movie`（座学の動画）・`make-practice-movie`（実践の動画）
- コースの基本情報・画像・長文の入れ方：`udemy-exam-prep` の `create-udemy-course`
- 演習テスト（practice test）：`udemy-exam-prep` の `udemy-bulk-upload` / `upload-practice-tests`
- 教訓の置き場：`references/self-improvement.md`（Udemy の操作で踏んだことは「Udemy 一般」として講座の教訓ファイルに書く）
