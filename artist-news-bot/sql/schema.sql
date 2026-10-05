-- artist-news-bot schema for Supabase / PostgreSQL.
-- Supabase: SQL Editor に貼り付けて実行。アプリ起動時の自動作成(create_all)と同じ構造に制約を追加したもの。

create table if not exists articles (
    id                varchar(36) primary key,
    artist_key        varchar(64) not null,
    title             text not null,
    url               text not null,
    canonical_url     text,
    url_hash          varchar(64) not null,          -- sha256(normalized canonical url)
    content_hash      varchar(64),                   -- sha256(normalized title + body)
    source_name       varchar(200),
    source_priority   integer not null default 9,    -- 1=official ... 7=news search
    published_at      timestamptz,
    discovered_at     timestamptz not null default now(),
    raw_text          text,
    summary           text,
    relevance_score   integer check (relevance_score between 0 and 100),
    importance_score  integer check (importance_score between 0 and 100),
    reliability_score integer check (reliability_score between 0 and 100),
    ai_reason         text,
    status            varchar(20) not null default 'discovered'
                      check (status in ('discovered', 'rejected', 'candidate', 'posted')),
    error_message     text,
    updated_at        timestamptz not null default now(),
    constraint uq_articles_artist_url unique (artist_key, url_hash)
);
create index if not exists ix_articles_artist_key on articles (artist_key);
create index if not exists ix_articles_content_hash on articles (content_hash);
create index if not exists ix_articles_status on articles (status);

create table if not exists posts (
    id                      varchar(36) primary key,
    article_id              varchar(36) not null unique references articles (id),
    generated_text          text not null,
    status                  varchar(20) not null default 'candidate'
                            check (status in ('candidate', 'notified', 'approved', 'posted',
                                              'failed', 'uncertain', 'rejected')),
    action_token_hash       varchar(64),             -- sha256 of the ntfy button token (never the token)
    action_token_expires_at timestamptz,
    created_at              timestamptz not null default now(),
    notified_at             timestamptz,
    notify_attempts         integer not null default 0,
    approved_at             timestamptz,
    rejected_at             timestamptz,
    posted_at               timestamptz,
    x_post_id               varchar(64),
    x_response              text,
    error_message           text,
    updated_at              timestamptz not null default now()
);
create index if not exists ix_posts_status on posts (status);

-- Supabase exposes the public schema through its REST API. The app connects directly with the
-- postgres role (which bypasses RLS), so enable RLS with no policies to block anon/authenticated keys.
alter table articles enable row level security;
alter table posts enable row level security;
