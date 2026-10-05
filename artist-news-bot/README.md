# artist-news-bot

**原因は自分にある。（ゲンジブ）武藤潤** さんの最新情報を収集し、AI で判定・要約して iPhone (ntfy) に通知、
**人間が「承認」をタップしたときだけ** X に投稿するシステム。完全自動投稿はしない。

> 現在の実装範囲: **Phase 1〜3**（RSS 収集 → AI → DB → ntfy → 承認 → X 投稿）。設計の詳細は [docs/DESIGN.md](docs/DESIGN.md)。

## システム概要

```
収集 → ルール判定(除外語/名前/鮮度) → 重複判定(URL・本文) → AI判定・要約・文案 → DB保存
  → ntfy 通知 [承認][却下][元記事] → 承認API → X API 投稿 → 投稿完了通知
```

- 投稿文の見出し・元記事URLはコードが付与し、AI が書くのは本文（事実のみ）だけ。AI 出力中の URL は除去する。
- X の文字数は weighted length（日本語・絵文字=2、URL=23）で 280 以内に収める。超える場合は文単位で削る。
- 承認は「署名トークン + 条件付き UPDATE」で、二重タップ・同時タップでも投稿は1回。

## ディレクトリ構成

```
artist-news-bot/
├── .env.example              環境変数の雛形（.env は Git 管理外）
├── config/artists.example.yaml  アーティスト設定（複数対応のリスト形式）
├── sql/schema.sql            Supabase/PostgreSQL 用 DDL
├── docs/DESIGN.md            アーキテクチャ・状態遷移・セキュリティ設計
├── src/newsbot/
│   ├── cli.py                CLI（init-db / ingest-dummy / collect / resend / list / resolve / serve）
│   ├── api.py                FastAPI: POST /api/approve/{id}, /api/reject/{id}, GET /healthz
│   ├── pipeline.py           収集→判定→保存→通知
│   ├── approval.py           承認・却下・X投稿（冪等）
│   ├── ai/                   AI 判定（Anthropic / fake）とプロンプト
│   ├── collectors/           情報源（rss.py: RSS/Atom、dummy.py: 動作確認用）
│   ├── notifier.py           ntfy 送信
│   ├── x_client.py           X API v2 クライアント
│   ├── text.py / urls.py / tokens.py  文字数計算・URL正規化・トークン
│   ├── models.py / db.py     DB モデル
│   └── scheduler.py          定期実行（APScheduler）
└── tests/
```

## 必要な外部サービス / API

| サービス | 用途 | 備考 |
|---|---|---|
| Anthropic API | 記事判定・要約・投稿文生成 | `AI_PROVIDER=fake` ならキー無しで動作確認可 |
| ntfy (ntfy.sh またはセルフホスト) + iPhone の ntfy アプリ | 通知・承認ボタン | |
| X API (Developer Console) | 投稿 | 有料。下記「X Developer 設定」参照 |
| Supabase (PostgreSQL) | DB | 開発時は SQLite で可 |
| HTTPS で到達できるホスト | 承認 API | iPhone から直接叩くため公開 URL が必要 |

## セットアップ

```bash
cd artist-news-bot
python3.11 -m venv .venv && source .venv/bin/activate   # uv でも可
pip install -e ".[dev]"
cp .env.example .env                       # 値を埋める
cp config/artists.example.yaml config/artists.yaml   # アーティスト情報を書く
python -m newsbot init-db
```

### .env 設定項目

| 変数 | 説明 | 既定値 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./newsbot.db` または `postgresql+psycopg://...` | sqlite |
| `ARTISTS_CONFIG` | アーティスト設定ファイル | `config/artists.yaml` |
| `LOG_LEVEL` / `LOG_FILE` | ログレベル / JSON Lines ログの出力先 | `INFO` / なし |
| `AI_PROVIDER` | `anthropic` / `fake` | `anthropic` |
| `ANTHROPIC_API_KEY` | Anthropic API キー | |
| `AI_MODEL` / `AI_EFFORT` | モデル / 推論の深さ (`low`〜`max`) | `claude-opus-5-5` / `medium` |
| `MIN_RELEVANCE_SCORE` / `MIN_IMPORTANCE_SCORE` / `MIN_RELIABILITY_SCORE` | 通知する閾値 | 70 / 50 / 60 |
| `MAX_ARTICLE_AGE_HOURS` | これより古い記事は AI に回さず却下 | 72 |
| `NTFY_SERVER` / `NTFY_TOPIC` / `NTFY_TOKEN` | ntfy サーバー / トピック / アクセストークン | `https://ntfy.sh` |
| `PUBLIC_BASE_URL` | 承認 API の公開 URL（https） | |
| `ACTION_TOKEN_TTL_HOURS` | 承認トークンの有効期限 | 48 |
| `X_API_KEY` / `X_API_SECRET` / `X_ACCESS_TOKEN` / `X_ACCESS_TOKEN_SECRET` | X の OAuth 1.0a 認証情報 | |
| `X_DRY_RUN` | `true` の間は X に送らずログのみ | `true` |
| `ENABLE_SCHEDULER` / `COLLECT_INTERVAL_MINUTES` | 定期収集の有効化 / 間隔(分) | `false` / 10 |

### DB 作成

- **開発**: SQLite。`python -m newsbot init-db` でテーブル作成。
- **Supabase**: ダッシュボードの SQL Editor で `sql/schema.sql` を実行し、
  Project Settings → Database の接続文字列を `postgresql+psycopg://...` 形式で `DATABASE_URL` に設定。
  `schema.sql` は RLS を有効化（ポリシー無し）しており、Supabase の REST API（anon キー）からは読めない。
  アプリは postgres ロールで直結するため影響しない。

### ntfy 設定

1. iPhone に ntfy アプリを入れ、`NTFY_TOPIC` と同じトピックを購読する。
2. トピック名は推測不可能なランダム文字列にする（`.env.example` に生成コマンドあり）。
3. **重要**: 通知には承認トークンが含まれる。ntfy.sh の公開トピックは「トピック名を知っている人は誰でも購読できる」ため、
   トピック名が漏れると第三者が承認できてしまう。運用ではアクセス制御付きトピック（ntfy の有料プランの予約トピック
   またはセルフホスト + ACL）と `NTFY_TOKEN` の利用を推奨。トークン有効期限と1回限りの状態遷移で被害は限定している。
4. 承認ボタンは iPhone から `PUBLIC_BASE_URL` へ直接 POST する。サーバーは HTTPS で外部から到達できる必要がある
   （VPS + Caddy、Fly.io / Render 等、自宅 PC なら Cloudflare Tunnel など）。

### X Developer 設定

1. X Developer Console でアプリを作成。
2. User authentication settings で App permissions を **Read and write** にする。
3. その後に Access Token / Secret を**生成（再生成）**する（権限変更前に発行したトークンは read のまま）。
4. API Key / Secret と Access Token / Secret を `.env` に設定し、確認できたら `X_DRY_RUN=false`。
5. 投稿は公式 API `POST https://api.x.com/2/tweets`（OAuth 1.0a User Context）のみ。ブラウザ自動操作は使わない。

## 起動方法

```bash
# Phase 1: ダミー記事を1件流す（AI判定→DB保存→ntfy通知）
python -m newsbot ingest-dummy --url https://example.com/news/1
python -m newsbot ingest-dummy --url https://example.com/news/1   # 2回目は duplicate

# Phase 2: 承認 API を起動（iPhone の「承認」でここが呼ばれる）
python -m newsbot serve --port 8000

# 運用コマンド
python -m newsbot list [--status notified]         # 投稿候補の一覧
python -m newsbot resend                            # ntfy 送信失敗分の再送
python -m newsbot check-sources                     # 各フィードの取得可否と該当件数を確認
python -m newsbot collect                           # 収集を1回実行
python -m newsbot resolve <post_id> --posted <X_ID> # 結果不明(uncertain)を手動で確定
python -m newsbot resolve <post_id> --not-posted    # 未投稿と確認 → 再承認ボタン付き通知を再送
```

`ENABLE_SCHEDULER=true` で `serve` 中に `COLLECT_INTERVAL_MINUTES` ごとに収集・AI 再判定・通知再送が走る。

## 情報源（config/artists.yaml の `sources`）

| 優先 | 情報源 | 状態 |
|---|---|---|
| 1 公式 | 原因は自分にある。公式サイト (genjibu.jp) | RSS 有無が未確認のため無効。HTML スクレイピングはしない |
| 4 音楽メディア | 音楽ナタリー / Real Sound の RSS | 有効（URL は要 `check-sources` 確認） |
| 7 ニュース検索 | Google ニュース RSS（"武藤潤" OR "ゲンジブ" OR "原因は自分にある。"） | 有効。リンクは news.google.com 経由 |

- フィードは記事タイトル・概要に名前（空白違いも同一視）またはグループ名が含まれるものだけ取り込む。
- `include_group_news: true` でグループ全体のニュースも対象（AI にも同じ方針を渡す）。
- 取得は条件付き GET（ETag / Last-Modified）で、変化がなければ本文を再取得しない。
- 1つのフィードが落ちても他は継続し、`collect_error` としてログに残る。

## ログ

JSON Lines で標準出力（と `LOG_FILE`）に出す。`event` フィールドで絞り込める:
`collect` / `collect_error` / `discovered` / `dedupe` / `judge` / `ai_error` / `ntfy_sent` / `ntfy_error` /
`notified` / `approved` / `approve_noop` / `rejected` / `auth_failed` / `x_posted` / `x_error` / `x_uncertain` / `tick`

```bash
grep '"event": "x_error"' logs/newsbot.jsonl
```

## テスト

```bash
pytest -q                                       # SQLite
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/newsbot_test pytest -q   # PostgreSQL
```

| 要件 | テスト |
|---|---|
| 同じ記事を2回取得しても再通知されない | `test_same_article_twice_is_not_renotified` |
| 承認を2回押しても2回投稿されない | `test_double_approve_posts_once`, `test_concurrent_approve_claims_once` |
| X API エラー時に DB 状態が壊れない | `test_x_api_error_marks_failed_and_allows_retry`, `test_uncertain_x_result_is_never_auto_retried` |
| 不正 token では投稿できない | `test_invalid_token_cannot_post`, `test_expired_token_rejected`, `test_unknown_post_and_other_posts_token_forbidden` |
| AI API エラー時に落ちない | `test_ai_error_does_not_crash_and_is_retried`, `test_failures_become_ai_error` |
| ntfy エラー時に再送可能 | `test_ntfy_error_can_be_resent` |

## セキュリティ

- API キー類は `.env` のみ（`.gitignore` 済み）。コードに直書きしない。
- 承認 URL は推測不可能な UUID + 256bit トークン（ハッシュ保存・有効期限付き・Authorization ヘッダ）。
- SQL は SQLAlchemy のパラメータバインドのみ（文字列連結の SQL なし）。
- 記事本文は AI プロンプト内で「データ」として扱い、記事中の指示には従わないよう指示している。
- API ドキュメント (`/docs`) は無効化。
