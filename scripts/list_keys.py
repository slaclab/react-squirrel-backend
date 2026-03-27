import asyncio
from argparse import ArgumentParser
from datetime import datetime

from app.db.session import async_session_maker
from app.schemas.api_key import ApiKeyDTO
from app.services.api_key_service import ApiKeyService


def _fmt(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-4]
    return str(value)


def print_table(models: list[ApiKeyDTO]) -> None:
    if not models:
        print("(no results)")
        return

    headers = list(type(models[0]).model_fields.keys())
    rows = [[_fmt(getattr(m, h)) for h in headers] for m in models]

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    fmt = "| " + " | ".join(f"{{:<{w}}}" for w in widths) + " |"

    print(sep)
    print(fmt.format(*headers))
    print(sep)
    for row in rows:
        print(fmt.format(*row))
    print(sep)


async def main(active_only):
    async with async_session_maker() as session:
        api_key_service = ApiKeyService(session)
        api_keys = await api_key_service.list_keys(active_only)
    print_table(api_keys)


if __name__ == "__main__":
    parser = ArgumentParser(description="List stored API keys (optionally list only active keys)")
    parser.add_argument("-a", "--active-only", action="store_true", help="Only list the active API Keys")
    args = parser.parse_args()

    asyncio.run(main(**args.__dict__))
