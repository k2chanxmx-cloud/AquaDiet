
# AquaDiet v1

水色UIの、体重・食事・運動・筋肉痛・AIコメントをまとめるPWAです。

## 1. Supabase
SupabaseのSQL Editorで `schema.sql` を実行してください。

## 2. 環境変数
Renderに以下を設定します。

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `OPENAI_API_KEY`
- `OPENAI_MODEL=gpt-5-mini`

## 3. Render
Build Command:
`pip install -r requirements.txt`

Start Command:
`gunicorn app:app --timeout 120`

## 主な機能
- 日別の体重記録
- 前回測定比
- 食事行の追加・削除
- 朝食 / 昼食 / 夕飯 / 夜食 / 間食プルダウン
- 食事ごとの「嘔吐した」チェック
- 腹筋 / 腹斜筋 / スクワット / ジム / パーソナル
- 運動メモ
- 筋肉痛の筋肉名タグ
- AIコメント
- キャラクター画像をCSSでシルエット表示
- 履歴
- 体重グラフ
- PWA

## 補足
v1は1ユーザー用のシンプル構成です。
公開URLを他人に知られる可能性がある場合は、次版でログイン/PINを追加してください。


## v1.1変更
- UIをグリーン系に変更
- キャラクターを最新WEBP画像へ差し替え
- キャラクターをカラー表示
- AIコメントのjson importエラーを修正

## v1.2変更
- キャラクター表示を大きく調整
- AIコメント吹き出しを拡大
- AIコメントを180〜320文字程度に拡張
- 「記録を保存」で保存後にAIコメントを自動生成
- 「AIコメントをもらう」単独ボタンを削除


## FINAL版
- iPhoneホーム画面から起動してもSafari（browser mode）で開く仕様
  - standalone PWAで発生したソフトキーボード不具合回避のため
- 食事追加ボタンは食事一覧の下
- 過去日付はページ再読み込み方式
- 保存後にAIコメントを自動生成
- AIコメントは約800〜1000文字
- あきおちゃん口調設定を反映
- OpenAI API timeout 150秒 / Gunicorn timeout 180秒
- Service WorkerはAPI通信をキャッシュしない


## FULL FINAL v2
- iPhoneホーム画面からSafari（browser mode）で開く仕様
- 保存後にAIコメント自動生成
- AIコメントは300〜500文字・5〜8文
- AIコメント欄は内容に合わせて縦に自動伸長
- OpenAI timeout 150秒 / max_output_tokens 1200
- Gunicorn timeout 180秒
- Service WorkerはAPI通信をキャッシュしない


## FULL FINAL v3
- AIコメントは300〜500文字・5〜8文のまま
- max_output_tokensを3000へ拡張
- reasoning effortをminimalへ設定
- output_textが空の場合、OpenAIレスポンス状態をRenderログへ出力


## v4 ツイート機能
- 下部メニューに「ツイート」を追加
- 当日の体重 / 朝昼夜 / 間食 / 夜食 / 運動 / 筋肉痛から140字以内で自動生成
- 手動編集 / 再生成 / 保存 / コピー
- 日付ごとにtweet_logsへ保存
- 過去90件を一覧表示

### 既存Supabaseへの追加
`schema.sql` 末尾に追加された `tweet_logs` のCREATE TABLE文をSQL Editorで実行してください。
