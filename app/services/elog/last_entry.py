"""Per-(api_key, logbook set) last-entry tracking for the elog plugin.

Used by the PostToElogDialog to pre-fill the "Follow up previous post" field.
The same row advances on both fresh creates and follow-ups, so the chain
naturally walks forward as the operator posts hourly snapshots.
"""
import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.models.elog_last_entry import ElogLastEntry

_MAX_KEY_LEN = 1024


def compute_logbooks_key(logbooks: list[str]) -> str:
    """Deterministically derive the scope key from a logbook list.

    Trims, drops empties, dedupes, sorts, joins with ``\\n``. Falls back to a
    SHA-256 prefix when the joined string would exceed the column width.
    """
    cleaned = sorted({lb.strip() for lb in logbooks if lb and lb.strip()})
    if not cleaned:
        raise ValueError("at least one logbook required")
    key = "\n".join(cleaned)
    if len(key) > _MAX_KEY_LEN:
        return "sha256:" + hashlib.sha256(key.encode()).hexdigest()
    return key


async def get_last_entry_id(db: AsyncSession, *, api_key_id: str, logbooks: list[str]) -> str | None:
    key = compute_logbooks_key(logbooks)
    stmt = select(ElogLastEntry.entry_id).where(
        ElogLastEntry.api_key_id == api_key_id,
        ElogLastEntry.logbooks_key == key,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def upsert_last_entry(db: AsyncSession, *, api_key_id: str, logbooks: list[str], entry_id: str) -> None:
    key = compute_logbooks_key(logbooks)
    stmt = (
        insert(ElogLastEntry)
        .values(api_key_id=api_key_id, logbooks_key=key, entry_id=entry_id)
        .on_conflict_do_update(
            index_elements=["api_key_id", "logbooks_key"],
            set_={"entry_id": entry_id},
        )
    )
    await db.execute(stmt)
    await db.commit()
