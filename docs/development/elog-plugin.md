# E-log Plugin Guide

Squirrel posts snapshots to an electronic logbook through a pluggable adapter
so different labs can use different e-log systems. The in-tree adapter targets
[elog-plus](https://github.com/slaclab/elog-plus); writing your own is a matter
of subclassing [`ElogAdapter`][app.services.elog.base.ElogAdapter] and
registering it.

## Enabling the shipped elog-plus adapter

Set these environment variables (via `.env` or the shell):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SQUIRREL_ELOG_PROVIDER` | yes | `""` (disabled) | `elog_plus` to enable the shipped adapter. |
| `SQUIRREL_ELOG_PLUS_BASE_URL` | yes | — | e.g. `https://elog.lab.org` |
| `SQUIRREL_ELOG_PLUS_TOKEN` | yes | — | Application JWT minted via elog-plus' `POST /v1/applications`. |
| `SQUIRREL_ELOG_PLUS_AUTH_HEADER` | no | `x-vouch-idp-accesstoken` | Matches `ELOG_PLUS_AUTH_HEADER` on the elog-plus service. |
| `SQUIRREL_ELOG_DEFAULT_LOGBOOKS` | no | `[]` | JSON list of logbook IDs preselected in the post dialog. |
| `SQUIRREL_ELOG_PROXY_URL` | no | `""` | Outbound HTTP(S) proxy for e-log calls (control-room gateways). |

When `SQUIRREL_ELOG_PROVIDER` is empty or unknown, `GET /v1/elog/config`
returns `{enabled: false}` and the frontend hides the "Post to Elog" button.

## Writing a new adapter

An adapter is a class that implements three async methods. All inputs and
outputs are plain Pydantic models — you don't need to touch FastAPI.

### 1. Subclass `ElogAdapter`

Create a file under `app/services/elog/`, for example
`app/services/elog/mylab_elog.py`:

```python
import httpx

from app.services.elog.base import (
    ElogAdapter,
    ElogEntryRequest,
    ElogEntryResult,
    ElogLogbook,
    ElogTag,
)


class MyLabElogAdapter(ElogAdapter):
    def __init__(self, base_url: str, token: str, proxy_url: str | None = None):
        if not base_url or not token:
            raise ValueError("base_url and token are required")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
            proxy=proxy_url or None,
            trust_env=False,
        )

    async def list_logbooks(self) -> list[ElogLogbook]:
        resp = await self._client.get("/logbooks")
        resp.raise_for_status()
        return [ElogLogbook(id=x["id"], name=x["name"]) for x in resp.json()]

    async def list_tags(self, logbook_id: str) -> list[ElogTag]:
        resp = await self._client.get(f"/logbooks/{logbook_id}/tags")
        resp.raise_for_status()
        return [ElogTag(id=x["id"], name=x["name"]) for x in resp.json()]

    async def create_entry(self, request: ElogEntryRequest) -> ElogEntryResult:
        body = f"Posted by {request.author} via Squirrel\n\n{request.body_markdown}"
        resp = await self._client.post(
            "/entries",
            json={
                "logbooks": request.logbooks,
                "title": request.title,
                "body": body,
                "tags": request.tags,
            },
        )
        resp.raise_for_status()
        return ElogEntryResult(id=resp.json()["id"])

    async def close(self) -> None:
        await self._client.aclose()
```

### 2. Register it

Add a factory to `app/services/elog/__init__.py`:

```python
from app.services.elog.mylab_elog import MyLabElogAdapter


def _build_mylab(settings: Settings) -> ElogAdapter:
    return MyLabElogAdapter(
        base_url=settings.mylab_elog_base_url,
        token=settings.mylab_elog_token,
        proxy_url=settings.elog_proxy_url or None,
    )


ELOG_PROVIDERS: dict[str, Callable[[Settings], ElogAdapter]] = {
    "elog_plus": _build_elog_plus,
    "mylab": _build_mylab,
}
```

### 3. Add settings

In `app/config.py`:

```python
mylab_elog_base_url: str = ""
mylab_elog_token: str = ""
```

### 4. Turn it on

```
SQUIRREL_ELOG_PROVIDER=mylab
SQUIRREL_MYLAB_ELOG_BASE_URL=https://elog.mylab.org
SQUIRREL_MYLAB_ELOG_TOKEN=...
```

## Contract

`ElogAdapter` methods receive and return:

- `ElogLogbook(id, name)` — a target the user can post into. IDs must round-trip
  unchanged through `list_tags` and `create_entry`.
- `ElogTag(id, name)` — a tag attached to an entry within a logbook.
- `ElogEntryRequest` — what the frontend sends. Key fields:
  - `logbooks: list[str]` — at least one logbook ID.
  - `title: str` (≤ 255 chars)
  - `body_markdown: str` — user-edited markdown. Convert to HTML here if your
    e-log renders raw.
  - `tags: list[str]` — tag IDs.
  - `author: str` — stamped by the route from the API key's `appName`; not
    trusted from the client.
  - `snapshot_id: str | None` — for your own auditing if useful.
- `ElogEntryResult(id, url=None)` — returned to the frontend after posting.

## Error handling

Raise `httpx.HTTPStatusError` / `httpx.TimeoutException` for upstream failures.
The `/v1/elog` router translates these into `502` / `504` so the frontend can
surface a useful error. Validation errors on input fail before reaching the
adapter thanks to Pydantic.

## Testing

Implementations should follow
[`tests/test_services/test_elog_plus.py`](../../tests/test_services/test_elog_plus.py):
construct the adapter against an `httpx.MockTransport` so tests stay
hermetic. Route-level tests can use
[`tests/mocks/elog_mock.py::MockElogAdapter`](../../tests/mocks/elog_mock.py)
by overriding the `_get_elog_adapter` dependency.
