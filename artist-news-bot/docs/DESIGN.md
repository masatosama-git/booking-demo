# 設計メモ

## 1. アーキテクチャ

```
                  ┌──────────────── 1 プロセス (FastAPI + APScheduler) ────────────────┐
 情報源            │                                                                   │
 (RSS/API/検索) ──▶ collectors ─▶ pipeline ─▶ ルール判定 ─▶ AI判定+要約+文案 ─▶ DB保存   │
                  │                (URL/本文ハッシュで重複排除)                ↓          │
                  │                                                     ntfy 送信 ──────┼──▶ iPhone
                  │                                                                   │      │
                  │  POST /api/approve/{id}  ◀─────────── Bearer トークン ────────────────┼──────┘ [承認]
                  │     └─ 条件付きUPDATEでロック ─▶ X API v2 POST /2/tweets ─▶ posted     │
                  │  POST /api/reject/{id}   ◀──────────────────────────────────────────┼─────── [却下]
                  └───────────────────────────────────────────────────────────────────┘
                                         │
                                Supabase / PostgreSQL
```

**1プロセス構成にした理由**: 承認APIは iPhone からの HTTP を常時受ける必要があるため常駐サーバーが必須。
収集も同じプロセスの APScheduler で回せば、デプロイ対象が1つで済む。
GitHub Actions の cron は「承認APIをホストできない」「スケジュールの最小間隔が5分で、混雑時に遅延する」ため不採用。

## 2. 状態遷移

articles: `discovered → rejected | candidate → posted`
（AI エラー時は `discovered` のまま残り、次回 tick で再判定）

posts:
```
candidate ──ntfy成功──▶ notified ──承認──▶ approved ──X成功──▶ posted
   │  ▲ (ntfy失敗→再送)      │                │
   │  └──────────────────────┤                ├─X 4xx(確実に未投稿)──▶ failed ──承認(新トークン)──▶ approved
   └────────却下─────────────┴──▶ rejected     └─タイムアウト/5xx──▶ uncertain（自動再試行しない。CLI resolve で確定）
```

## 3. 二重投稿防止

- `UPDATE posts SET status='approved' WHERE id=:id AND status IN ('candidate','notified','failed')`
  の **影響行数が1の呼び出しだけ** が X へ投稿する。DB の行ロックで直列化されるため、同時タップでも1回のみ。
- X 呼び出しの結果が不明（タイムアウト・5xx）なら `uncertain` にして自動再試行しない。
- 結果書き込みも `WHERE status='approved'` 付きで、最終状態を上書きしない。
- 1記事につき post は1件（`posts.article_id UNIQUE`）、記事は `(artist_key, url_hash) UNIQUE`。

## 4. 承認トークン

- 通知ごとに `secrets.token_urlsafe(32)`（256bit）を発行し、DB には SHA-256 ハッシュのみ保存。
- ntfy の http アクションの `Authorization: Bearer` ヘッダで送る（URL に載せないのでアクセスログに残らない）。
- 有効期限あり（既定 48h）。再通知・失敗後の再通知ではトークンを再発行し、旧トークンは無効。
- 存在しない post / 不正トークンはどちらも 403（ID の探索を防ぐ）。

## 5. 実装フェーズ

| Phase | 内容 | 状態 |
|---|---|---|
| 1 | ダミー記事 → AI判定・要約 → DB保存 → ntfy通知 | ✅ |
| 2 | ntfy承認 → 承認API → X投稿 → 完了通知 | ✅ |
| 3 | RSS / 公開API / 検索API コレクタ | 未着手（`collectors/` に追加し `build_context` で登録） |
| 4 | 重複排除の強化（タイトル類似度・同一トピック集約） | URL/本文ハッシュ/AI判定のみ実装済 |
| 5 | 複数情報源（公式 > 事務所 > レーベル > 音楽メディア ...） | `source_priority` 列のみ用意 |
| 6 | 精度改善（評価セット・プロンプト調整） | 未着手 |
