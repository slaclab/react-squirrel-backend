"""Unit tests for :class:`ElogPlusAdapter` against a fake transport."""
import httpx
import pytest

from app.services.elog.base import ElogEntryRequest
from app.services.elog.elog_plus import ElogPlusAdapter


def _make_adapter(handler, **overrides) -> ElogPlusAdapter:
    """Build an adapter whose HTTP client routes requests through ``handler``."""
    adapter = ElogPlusAdapter(
        base_url="http://elog.test",
        token="test-token",
        **overrides,
    )
    adapter._client = httpx.AsyncClient(
        base_url="http://elog.test",
        headers={adapter._auth_header: "test-token"},
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    return adapter


class TestListLogbooks:
    async def test_parses_envelope(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/logbooks"
            assert request.headers["x-vouch-idp-accesstoken"] == "test-token"
            return httpx.Response(
                200,
                json={
                    "errorCode": 0,
                    "payload": [
                        {"id": "lb1", "name": "Ops", "tags": []},
                        {"id": "lb2", "name": "Commissioning", "tags": []},
                    ],
                },
            )

        adapter = _make_adapter(handler)
        try:
            logbooks = await adapter.list_logbooks()
        finally:
            await adapter.close()

        assert [lb.id for lb in logbooks] == ["lb1", "lb2"]
        assert [lb.name for lb in logbooks] == ["Ops", "Commissioning"]

    async def test_tolerates_missing_envelope(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"id": "lb1", "name": "Ops"}])

        adapter = _make_adapter(handler)
        try:
            logbooks = await adapter.list_logbooks()
        finally:
            await adapter.close()

        assert len(logbooks) == 1
        assert logbooks[0].id == "lb1"


class TestCreateEntry:
    async def test_posts_entry_with_author_attribution(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/entries"
            assert request.method == "POST"
            import json

            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"errorCode": 0, "payload": "entry-abc"})

        adapter = _make_adapter(handler)
        req = ElogEntryRequest(
            logbooks=["lb1"],
            title="Snapshot: foo",
            body_markdown="# hello",
            tags=["t1"],
            author="ConsoleUser",
            snapshot_id="snap-123",
        )

        try:
            result = await adapter.create_entry(req)
        finally:
            await adapter.close()

        assert result.id == "entry-abc"
        body = captured["body"]
        assert body["logbooks"] == ["lb1"]
        assert body["title"] == "Snapshot: foo"
        assert body["tags"] == ["t1"]
        assert body["additionalAuthors"] == ["ConsoleUser"]
        # Attribution prepended to body
        assert body["text"].startswith("_Posted by **ConsoleUser** via Squirrel_")
        assert "# hello" in body["text"]

    async def test_raises_on_upstream_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"errorCode": 1, "errorMessage": "boom"})

        adapter = _make_adapter(handler)
        req = ElogEntryRequest(
            logbooks=["lb1"],
            title="T",
            body_markdown="b",
            author="A",
        )

        try:
            with pytest.raises(httpx.HTTPStatusError):
                await adapter.create_entry(req)
        finally:
            await adapter.close()


class TestAdapterConstruction:
    def test_rejects_empty_base_url(self):
        with pytest.raises(ValueError, match="base_url"):
            ElogPlusAdapter(base_url="", token="tok")

    def test_rejects_empty_token(self):
        with pytest.raises(ValueError, match="token"):
            ElogPlusAdapter(base_url="http://elog.test", token="")

    def test_custom_auth_header(self):
        adapter = ElogPlusAdapter(
            base_url="http://elog.test",
            token="tok",
            auth_header="Authorization",
        )
        assert adapter._client.headers["Authorization"] == "tok"

    def test_proxy_is_honored(self):
        # httpx builds an HTTPTransport with a proxy when `proxy=` is set; we can
        # only assert that construction succeeds here without hitting network.
        adapter = ElogPlusAdapter(
            base_url="http://elog.test",
            token="tok",
            proxy_url="http://proxy.lab.test:8080",
        )
        assert adapter._client is not None
