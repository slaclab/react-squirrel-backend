"""Unit tests for :class:`ElogPlusAdapter` against a fake transport."""
import json
from datetime import datetime

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


def _logbooks_directory_response() -> httpx.Response:
    """elog-plus' /v1/logbooks listing used by adapter id↔name resolvers."""
    return httpx.Response(
        200,
        json={
            "errorCode": 0,
            "payload": [
                {"id": "lb1", "name": "Operations"},
                {"id": "lb2", "name": "Commissioning"},
            ],
        },
    )


def _tags_directory_response_for_lb1() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "errorCode": 0,
            "payload": [
                {"id": "t1", "name": "Routine"},
                {"id": "t2", "name": "LCLS"},
            ],
        },
    )


class TestCreateEntry:
    async def test_posts_v1_json_with_author_attribution(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/logbooks":
                return _logbooks_directory_response()
            if request.url.path == "/v1/logbooks/lb1/tags":
                return _tags_directory_response_for_lb1()
            assert request.url.path == "/v1/entries"
            assert request.method == "POST"
            assert request.headers["content-type"].startswith("application/json")
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"errorCode": 0, "payload": "entry-abc"})

        adapter = _make_adapter(handler)
        # Frontend sends IDs; adapter passes IDs through to v1.
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
        assert body["tags"] == ["t1"]
        assert body["title"] == "Snapshot: foo"
        assert "<em>Posted by <strong>ConsoleUser</strong> via Squirrel</em>" in body["text"]
        assert "<h1>hello</h1>" in body["text"]
        assert "additionalAuthors" not in body
        assert "important" not in body
        assert "eventAt" not in body

    async def test_resolves_logbook_names_to_ids(self):
        """Names from the wire get resolved to IDs because v1 expects IDs."""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/logbooks":
                return _logbooks_directory_response()
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"errorCode": 0, "payload": "entry-xyz"})

        adapter = _make_adapter(handler)
        req = ElogEntryRequest(logbooks=["Operations"], title="T", body_markdown="b", author="A")

        try:
            await adapter.create_entry(req)
        finally:
            await adapter.close()

        assert captured["body"]["logbooks"] == ["lb1"]

    async def test_serializes_new_optional_fields(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/logbooks":
                return _logbooks_directory_response()
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"errorCode": 0, "payload": "entry-xyz"})

        adapter = _make_adapter(handler)
        req = ElogEntryRequest(
            logbooks=["lb1"],
            title="T",
            body_markdown="b",
            author="Alice",
            additional_authors=["bob@lab", "carol@lab"],
            important=True,
            event_at=datetime(2026, 4, 29, 9, 30, 15),
        )

        try:
            await adapter.create_entry(req)
        finally:
            await adapter.close()

        body = captured["body"]
        assert body["important"] is True
        assert body["eventAt"] == "2026-04-29T09:30:15"
        assert body["additionalAuthors"] == ["bob@lab", "carol@lab"]

    async def test_omits_additional_authors_when_none_selected(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/logbooks":
                return _logbooks_directory_response()
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"errorCode": 0, "payload": "entry-1"})

        adapter = _make_adapter(handler)
        req = ElogEntryRequest(logbooks=["lb1"], title="T", body_markdown="b", author="Alice")

        try:
            await adapter.create_entry(req)
        finally:
            await adapter.close()

        assert "additionalAuthors" not in captured["body"]

    async def test_raises_on_upstream_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/logbooks":
                return _logbooks_directory_response()
            return httpx.Response(500, json={"errorCode": 1, "errorMessage": "boom"})

        adapter = _make_adapter(handler)
        req = ElogEntryRequest(logbooks=["lb1"], title="T", body_markdown="b", author="A")

        try:
            with pytest.raises(httpx.HTTPStatusError):
                await adapter.create_entry(req)
        finally:
            await adapter.close()


class TestCreateFollowUp:
    @staticmethod
    def _logbooks_response() -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "errorCode": 0,
                "payload": [
                    {"id": "lb1", "name": "Operations"},
                    {"id": "lb2", "name": "Commissioning"},
                ],
            },
        )

    async def test_posts_to_v1_follow_ups_endpoint_as_json(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/logbooks":
                return TestCreateFollowUp._logbooks_response()
            assert request.url.path == "/v1/entries/parent-1/follow-ups"
            assert request.method == "POST"
            assert request.headers["content-type"].startswith("application/json")
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"errorCode": 0, "payload": "child-1"})

        adapter = _make_adapter(handler)
        req = ElogEntryRequest(
            logbooks=["lb1"],
            title="Hourly snapshot",
            body_markdown="follow-up body",
            author="Operator",
            important=True,
            event_at=datetime(2026, 4, 29, 10, 0, 0),
        )

        try:
            result = await adapter.create_follow_up("parent-1", req)
        finally:
            await adapter.close()

        assert result.id == "child-1"
        body = captured["body"]
        assert body["title"] == "Hourly snapshot"
        assert "<em>Posted by <strong>Operator</strong> via Squirrel</em>" in body["text"]
        assert "additionalAuthors" not in body
        assert body["important"] is True
        assert body["eventAt"] == "2026-04-29T10:00:00"

    async def test_resolves_logbook_names_to_ids(self):
        """v1 follow-ups auth treats logbooks as IDs, so the adapter must resolve names."""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/logbooks":
                return TestCreateFollowUp._logbooks_response()
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"errorCode": 0, "payload": "child-2"})

        adapter = _make_adapter(handler)
        # Frontend sends names, not IDs.
        req = ElogEntryRequest(
            logbooks=["Operations", "Commissioning"],
            title="T",
            body_markdown="b",
            author="A",
        )

        try:
            await adapter.create_follow_up("parent-1", req)
        finally:
            await adapter.close()

        assert captured["body"]["logbooks"] == ["lb1", "lb2"]

    async def test_resolves_tag_names_to_ids(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/logbooks":
                return TestCreateFollowUp._logbooks_response()
            if request.url.path == "/v1/logbooks/lb1/tags":
                return httpx.Response(
                    200,
                    json={
                        "errorCode": 0,
                        "payload": [
                            {"id": "tag-id-1", "name": "LCLS"},
                            {"id": "tag-id-2", "name": "Routine"},
                        ],
                    },
                )
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"errorCode": 0, "payload": "child-tag"})

        adapter = _make_adapter(handler)
        # Frontend sends tag names (case-insensitive match against elog-plus).
        req = ElogEntryRequest(
            logbooks=["Operations"],
            tags=["lcls", "Routine"],
            title="T",
            body_markdown="b",
            author="A",
        )

        try:
            await adapter.create_follow_up("parent-1", req)
        finally:
            await adapter.close()

        assert captured["body"]["logbooks"] == ["lb1"]
        assert captured["body"]["tags"] == ["tag-id-1", "tag-id-2"]

    async def test_passes_through_unknown_logbooks(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/logbooks":
                return TestCreateFollowUp._logbooks_response()
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"errorCode": 0, "payload": "child-3"})

        adapter = _make_adapter(handler)
        # Already an ID — passes through.
        req = ElogEntryRequest(logbooks=["lb1"], title="T", body_markdown="b", author="A")

        try:
            await adapter.create_follow_up("parent-1", req)
        finally:
            await adapter.close()

        assert captured["body"]["logbooks"] == ["lb1"]

    async def test_propagates_upstream_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/logbooks":
                return TestCreateFollowUp._logbooks_response()
            return httpx.Response(404, json={"errorCode": 1, "errorMessage": "no parent"})

        adapter = _make_adapter(handler)
        req = ElogEntryRequest(logbooks=["lb1"], title="T", body_markdown="b", author="A")

        try:
            with pytest.raises(httpx.HTTPStatusError):
                await adapter.create_follow_up("missing", req)
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
