from newsbot.text import MAX_WEIGHTED_LENGTH, compose_post, weighted_length
from newsbot.urls import normalize_url

URL = "https://natalie.mu/music/news/123456?utm_source=x"


def test_weighted_length_rules():
    assert weighted_length("abc") == 3
    assert weighted_length("あいう") == 6
    assert weighted_length("👇") == 2
    assert weighted_length("見て https://example.com/" + "a" * 200) == 4 + 1 + 23


def test_compose_includes_source_url_and_strips_ai_links():
    text = compose_post("〇〇 最新情報", "新曲発表。詳しくは https://evil.example を参照。", URL)
    assert text.startswith("【〇〇 最新情報】")
    assert text.endswith(f"詳細👇\n{URL}")
    assert "evil.example" not in text


def test_compose_fits_limit_by_dropping_sentences():
    body = "〇〇が新曲を発表した。" * 30
    text = compose_post("〇〇 最新情報", body, URL, hashtags=["〇〇"])
    assert weighted_length(text) <= MAX_WEIGHTED_LENGTH
    assert URL in text and "#〇〇" in text
    assert "…" not in text  # cut at a sentence boundary


def test_compose_hard_truncates_single_long_sentence():
    text = compose_post("〇〇 最新情報", "あ" * 300, URL)
    assert weighted_length(text) <= MAX_WEIGHTED_LENGTH and "…" in text and URL in text


def test_normalize_url():
    assert normalize_url("http://Example.com/a/?utm_medium=x&b=2&a=1#frag") == "https://example.com/a?a=1&b=2"


def test_heading_switches_between_member_and_group():
    from newsbot.config import ArtistProfile

    a = ArtistProfile(key="m", name="武藤潤", group="原因は自分にある。", group_aliases=["ゲンジブ"])
    assert a.heading("individual") == "武藤潤 最新情報"
    assert a.heading("group") == "原因は自分にある。最新情報"
    assert ArtistProfile(key="s", name="ソロ").heading("group") == "ソロ 最新情報"  # no group configured
