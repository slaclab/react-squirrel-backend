import sys
import asyncio
from argparse import ArgumentParser

from app.db.session import async_session_maker
from app.schemas.api_key import ApiKeyCreateDTO
from app.services.api_key_service import ApiKeyService


async def main(app_name: str, read: bool, write: bool):
    key_create_dto = ApiKeyCreateDTO(
        appName=app_name,
        readAccess=read,
        writeAccess=write,
    )

    try:
        async with async_session_maker() as session:
            api_key_service = ApiKeyService(session)
            api_key = await api_key_service.create_key(key_create_dto)
            await session.commit()
    except ValueError as e:
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
        f"API Key created successfully!\n"
        f"  App Name:   {api_key.appName}\n"
        f"  ID:         {api_key.id}\n"
        f"  Access:     {access}\n"
        f"  Created At: {api_key.createdAt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-4]}\n"
        f"  Token: {api_key.token}\n"
    )


if __name__ == "__main__":
    parser = ArgumentParser(description="Create a new API key")
    parser.add_argument("app_name", type=str, help="Name for the API key")
    parser.add_argument("-r", "--read", action="store_true", help="Read access for the API key")
    parser.add_argument("-w", "--write", action="store_true", help="Write access for the API key")
    args = parser.parse_args()

    if not args.read and not args.write:
        parser.error("At least one of --read or --write must be specified")

    asyncio.run(main(**args.__dict__))
