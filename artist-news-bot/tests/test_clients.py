import json

import httpx
import pytest
import requests

from newsbot.notifier import Notification, NotifyError, NtfyNotifier
from newsbot.x_client import XClient, XPostError, XPostUncertainError


def test_ntfy_publishes_json_with_auth():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "abc"})

    n = NtfyNotifier("https://ntfy.example/", "topic1", token="tk", transport=httpx.MockTransport(handler))
    acts = [{"action": "view", "label": str(i), "url": "https://e.com"} for i in range(5)]
    assert n.send(Notification(title="タイトル", message="本文", actions=acts)) == "abc"
    assert seen["url"] == "https://ntfy.example/"
    assert seen["auth"] == "Bearer tk"
    assert seen["body"]["topic"] == "topic1" and seen["body"]["title"] == "タイトル"
    assert len(seen["body"]["actions"]) == 3


def test_ntfy_http_error_raises_notify_error():
    n = NtfyNotifier("https://ntfy.example", "t", transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    with pytest.raises(NotifyError):
        n.send(Notification(title="t", message="m"))


class FakeSession:
    def __init__(self, status=None, body="", exc=None):
        self.status, self.body, self.exc = status, body, exc

    def post(self, url, **kw):
        if self.exc:
            raise self.exc
        r = requests.Response()
        r.status_code = self.status
        r._content = self.body.encode()
        return r


def _client(**kw):
    return XClient("k", "s", "t", "ts", session=FakeSession(**kw))


def test_x_success_returns_id():
    res = _client(status=201, body='{"data":{"id":"1846","text":"hi"}}').create_post("hi")
    assert res.post_id == "1846" and "1846" in res.raw_response


@pytest.mark.parametrize("kw,exc", [
    (dict(status=403, body='{"detail":"duplicate"}'), XPostError),
    (dict(status=429, body="rate"), XPostError),
    (dict(exc=requests.ConnectTimeout("x")), XPostError),
    (dict(status=503, body="down"), XPostUncertainError),
    (dict(exc=requests.ReadTimeout("x")), XPostUncertainError),
    (dict(status=200, body="not json"), XPostUncertainError),
])
def test_x_error_classification(kw, exc):
    with pytest.raises(exc):
        _client(**kw).create_post("hi")
