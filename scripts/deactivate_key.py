import sys
import asyncio
from argparse import ArgumentParser

from app.db.session import async_session_maker
from app.services.api_key_service import ApiKeyService


async def main(id: str | None = None):
    try:
        async with async_session_maker() as session:
            api_key_service = ApiKeyService(session)
            api_key = await api_key_service.deactivate_key(id)
            await session.commit()
    except (LookupError, ValueError) as e:
        print(e)
        sys.exit(1)

    access = ", ".join(
        filter(
            None,
            [
                "read" if api_key.readAccess else "",
                "write" if api_key.writeAccess else "",
            ],
        )
    )
    print(
        f"API Key deactivated successfully\n"
        f"  App Name:   {api_key.appName}\n"
        f"  ID:         {api_key.id}\n"
        f"  Access:     {access}\n"
        f"  Created At: {api_key.createdAt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-4]}\n"
        f"  Updated At: {api_key.updatedAt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-4]}\n"
    )


if __name__ == "__main__":
    parser = ArgumentParser(description="Deactivate an existing API key using its ID")
    parser.add_argument("id", type=str, help="ID of the API key to deactivate")
    args = parser.parse_args()

    asyncio.run(main(**args.__dict__))
