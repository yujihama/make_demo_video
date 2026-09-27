# 翻訳の手順（Claude Code が翻訳者になる）

`bin/demo translate scenes/<id>.yaml --lang <言語>` は、訳す文言を書き出して止まる（終了コード 3）。
あなたが字幕翻訳者として訳を `response.json` に書き、同じコマンドを再実行すると `scenes/<id>.<言語>.yaml` ができる。

## 1. 依頼を読む

依頼フォルダ `out/_handoff/translate-<シーン>-<言語>-<ハッシュ>/` の `request.md` に、次が書いてある。

- 動画の題名と、訳の決まり
- 訳す文言の一覧: `id` と `text`
  - `id` の例: `head:title`（題名）、`step:3:caption`（字幕）、`step:0:title`（章の題名）、`step:6:effect/countup/label`（数え上げの見出し）、`step:8:after/value`（比較カードの値）

元の言語と同じ内容でも、すべての `id` を返す（抜けがあると再実行時にエラーになる）。

## 2. 訳の決まり

- **字幕は短く。** 画面を見ながら読み切れる長さにする。英語はおよそ 15 字/秒で読まれる前提で判定される。意味を落とさない範囲で言い換えてよい
- `**語**` の強調記法は残し、訳文でも同じ意味の語を囲む
- 数値・金額・ファイル名・製品名は変えない（例: 8件 → 8 transactions / 1,850,000円 → JPY 1,850,000）
- アプリの画面は元の言語のまま映る。ボタン名などは画面の文字をそのまま引用せず、意味で訳す（例:「監査を実行」ボタン → "the Run button" ではなく "one click starts the audit"）
- 章の題名（`…:title`）は名詞句で短く。比較カードの値（`…/value`）は大きく表示されるので短く（"3 days" / "5 min"）
- 数え上げの単位（`…/countup/suffix`）は、訳すと不自然なら空文字 `""` にしてよい（"Findings 6" のように見出しで意味が通る）
- 定型文言（まとめ・早送り・保存しました・STEP）はツールが言語ごとに持っているので訳さない

## 3. 回答を書く

`response.json` の例:

```json
{
 "items": [
  {"id": "head:title", "text": "Expense audits in one click"},
  {"id": "step:0:title", "text": "Upload evidence"},
  {"id": "step:3:caption", "text": "**One click** starts the audit agent"},
  {"id": "step:6:effect/countup/suffix", "text": ""}
 ]
}
```

書いたら `bin/demo translate …` を再実行する。

## 4. 訳のあと

- `scenes/<id>.<言語>.yaml` は人が直してよい。`_src`（元の文言のハッシュ）は消さない
- 元の YAML の字幕を直したら `translate` をもう一度実行する。変わったステップだけが依頼に出る（人が直した訳は残る）
- `bin/demo make scenes/<id>.yaml --lang ja,<言語> --vision` で、訳した版も見た目の審査にかける（`language` と `layout` の観点で、はみ出しや訳抜けを見る）
