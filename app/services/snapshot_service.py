import logging
import math
from datetime import datetime
from typing import Any, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession


def _sanitize_for_json(value: Any) -> Any:
    """
    Sanitize a value for JSON storage.

    Converts NaN, Inf, -Inf to None since these are not valid JSON.
    Recursively handles lists and dicts.
    """
    if value is None:
        return None

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, list):
        return [_sanitize_for_json(v) for v in value]

    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}

    return value

from app.models.snapshot import Snapshot, SnapshotValue
from app.repositories.snapshot_repository import SnapshotRepository, SnapshotValueRepository
from app.repositories.pv_repository import PVRepository
from app.services.epics_service import EpicsService, EpicsValue
from app.services.redis_service import RedisService
from app.schemas.snapshot import (
    NewSnapshotDTO, SnapshotDTO, SnapshotSummaryDTO, PVValueDTO, EpicsValueDTO,
    RestoreRequestDTO, RestoreResultDTO, ComparisonResultDTO
)

logger = logging.getLogger(__name__)


class SnapshotService:
    """Service for snapshot operations with EPICS integration."""

    def __init__(
        self,
        session: AsyncSession,
        epics_service: EpicsService,
        redis_service: RedisService | None = None
    ):
        self.session = session
        self.snapshot_repo = SnapshotRepository(session)
        self.value_repo = SnapshotValueRepository(session)
        self.pv_repo = PVRepository(session)
        self.epics = epics_service
        self.redis = redis_service

    def _epics_to_dto(self, epics_val: EpicsValue) -> EpicsValueDTO | None:
        """Convert EPICS value to DTO."""
        if not epics_val.connected:
            return None
        return EpicsValueDTO(
            value=epics_val.value,
            status=epics_val.status,
            severity=epics_val.severity,
            timestamp=epics_val.timestamp,
            units=epics_val.units,
            precision=epics_val.precision,
            upper_ctrl_limit=epics_val.upper_ctrl_limit,
            lower_ctrl_limit=epics_val.lower_ctrl_limit
        )

    async def list_snapshots(self, title: str | None = None) -> list[SnapshotSummaryDTO]:
        """List all snapshots."""
        snapshots = await self.snapshot_repo.search(title=title)

        result = []
        for snap in snapshots:
            count = await self.snapshot_repo.get_value_count(snap.id)
            result.append(SnapshotSummaryDTO(
                id=snap.id,
                title=snap.title,
                comment=snap.comment,
                createdDate=snap.created_at,
                createdBy=snap.created_by,
                pvCount=count
            ))
        return result

    async def get_by_id(
        self,
        snapshot_id: str,
        limit: int | None = None,
        offset: int = 0
    ) -> SnapshotDTO | None:
        """
        Get snapshot with values.

        Args:
            snapshot_id: The snapshot ID
            limit: Max number of values to return (None = all)
            offset: Number of values to skip for pagination
        """
        snapshot = await self.snapshot_repo.get_with_values(snapshot_id, limit=limit, offset=offset)
        if not snapshot:
            return None

        # Get total count for pvCount (even when paginated)
        total_count = await self.value_repo.count_by_snapshot(snapshot_id)

        pv_values = [
            PVValueDTO(
                pvId=v.pv_id,
                pvName=v.pv_name,
                setpointValue=EpicsValueDTO(**v.setpoint_value) if v.setpoint_value else None,
                readbackValue=EpicsValueDTO(**v.readback_value) if v.readback_value else None,
                status=v.status,
                severity=v.severity,
                timestamp=v.timestamp
            )
            for v in snapshot.values
        ]

        return SnapshotDTO(
            id=snapshot.id,
            title=snapshot.title,
            comment=snapshot.comment,
            createdDate=snapshot.created_at,
            createdBy=snapshot.created_by,
            pvCount=total_count,
            pvValues=pv_values
        )

    async def create_snapshot(
        self,
        data: NewSnapshotDTO,
        created_by: str | None = None,
        progress_callback: Optional[Callable] = None
    ) -> SnapshotSummaryDTO:
        """
        Create a new snapshot by reading all PVs from EPICS.

        This is the critical high-performance path.
        """
        logger.info(f"Creating snapshot: {data.title}")
        start_time = datetime.now()

        try:
            # Get all PVs and their addresses
            pv_addresses = await self.pv_repo.get_all_addresses()
            logger.info(f"Found {len(pv_addresses)} PVs to snapshot")

            # Collect all unique addresses to read
            setpoint_map: dict[str, str] = {}  # address -> pv_id
            readback_map: dict[str, str] = {}  # address -> pv_id

            for pv_id, setpoint, readback, config in pv_addresses:
                if setpoint:
                    setpoint_map[setpoint] = pv_id
                if readback:
                    readback_map[readback] = pv_id

            all_addresses = list(set(setpoint_map.keys()) | set(readback_map.keys()))
            logger.info(f"Reading {len(all_addresses)} unique EPICS addresses")

            # Read all values from EPICS in parallel with progress reporting
            if progress_callback:
                epics_values = await self.epics.get_many_with_progress(all_addresses, progress_callback)
            else:
                epics_values = await self.epics.get_many(all_addresses)

            read_time = datetime.now()
            logger.info(f"EPICS read completed in {(read_time - start_time).total_seconds():.2f}s")

            # Debug: check how many values we got back
            connected_count = sum(1 for v in epics_values.values() if v.connected)
            logger.info(f"EPICS results: {len(epics_values)} total, {connected_count} connected")

            # Debug: sample a few keys to verify format
            sample_keys = list(epics_values.keys())[:3]
            logger.info(f"Sample EPICS keys: {sample_keys}")
            sample_setpoint_keys = list(setpoint_map.keys())[:3]
            logger.info(f"Sample setpoint map keys: {sample_setpoint_keys}")

            # Report progress: EPICS read complete, starting database save
            if progress_callback:
                await progress_callback(len(all_addresses), len(all_addresses), "Processing results...")

            # Create snapshot record
            snapshot = Snapshot(
                title=data.title,
                comment=data.comment,
                created_by=created_by
            )
            snapshot = await self.snapshot_repo.create(snapshot)

            # Build snapshot values
            snapshot_values = []
            pv_data: dict[str, dict] = {}  # pv_id -> {setpoint_value, readback_value}

            # Process setpoint values
            for address, pv_id in setpoint_map.items():
                if pv_id not in pv_data:
                    pv_data[pv_id] = {"setpoint": None, "readback": None, "address": address}
                epics_val = epics_values.get(address)
                if epics_val and epics_val.connected:
                    # Sanitize value to handle NaN/Inf which are not valid JSON
                    pv_data[pv_id]["setpoint"] = {
                        "value": _sanitize_for_json(epics_val.value),
                        "status": epics_val.status,
                        "severity": epics_val.severity,
                        "timestamp": epics_val.timestamp.isoformat() if epics_val.timestamp else None,
                        "units": epics_val.units,
                        "precision": epics_val.precision
                    }

            # Process readback values
            for address, pv_id in readback_map.items():
                if pv_id not in pv_data:
                    pv_data[pv_id] = {"setpoint": None, "readback": None, "address": address}
                epics_val = epics_values.get(address)
                if epics_val and epics_val.connected:
                    # Sanitize value to handle NaN/Inf which are not valid JSON
                    pv_data[pv_id]["readback"] = {
                        "value": _sanitize_for_json(epics_val.value),
                        "status": epics_val.status,
                        "severity": epics_val.severity,
                        "timestamp": epics_val.timestamp.isoformat() if epics_val.timestamp else None,
                        "units": epics_val.units,
                        "precision": epics_val.precision
                    }

            # Debug: check pv_data
            pv_with_setpoint = sum(1 for d in pv_data.values() if d.get("setpoint"))
            pv_with_readback = sum(1 for d in pv_data.values() if d.get("readback"))
            logger.info(f"pv_data: {len(pv_data)} total, {pv_with_setpoint} with setpoint, {pv_with_readback} with readback")

            # Create SnapshotValue records
            for pv_id, data_dict in pv_data.items():
                snapshot_values.append(SnapshotValue(
                    snapshot_id=snapshot.id,
                    pv_id=pv_id,
                    pv_name=data_dict.get("address", ""),
                    setpoint_value=data_dict.get("setpoint"),
                    readback_value=data_dict.get("readback"),
                    status=data_dict.get("setpoint", {}).get("status") if data_dict.get("setpoint") else None,
                    severity=data_dict.get("setpoint", {}).get("severity") if data_dict.get("setpoint") else None,
                    timestamp=datetime.now()
                ))

            logger.info(f"Created {len(snapshot_values)} SnapshotValue records")

            # Report progress: Saving to database
            if progress_callback:
                await progress_callback(len(all_addresses), len(all_addresses), f"Saving {len(snapshot_values)} values to database...")

            # Bulk insert values with progress tracking for large datasets
            await self.value_repo.bulk_create(snapshot_values, progress_callback=progress_callback)

            total_time = datetime.now()
            logger.info(f"Snapshot created in {(total_time - start_time).total_seconds():.2f}s "
                       f"({len(snapshot_values)} values)")

            return SnapshotSummaryDTO(
                id=snapshot.id,
                title=snapshot.title,
                comment=snapshot.comment,
                createdDate=snapshot.created_at,
                createdBy=snapshot.created_by,
                pvCount=len(snapshot_values)
            )
        except Exception as e:
            logger.exception(f"Error creating snapshot '{data.title}': {e}")
            raise

    async def create_snapshot_from_cache(
        self,
        data: NewSnapshotDTO,
        created_by: str | None = None,
        progress_callback: Optional[Callable] = None
    ) -> SnapshotSummaryDTO:
        """
        Create snapshot by reading from Redis cache (instant).

        This is much faster than direct EPICS reads when the cache is populated
        by the PV Monitor background service.
        """
        if not self.redis:
            logger.warning("Redis not available, falling back to direct EPICS read")
            return await self.create_snapshot(data, created_by, progress_callback)

        logger.info(f"Creating snapshot from cache: {data.title}")
        start_time = datetime.now()

        try:
            # Get all PVs and their addresses
            pv_addresses = await self.pv_repo.get_all_addresses()
            logger.info(f"Found {len(pv_addresses)} PVs to snapshot")

            if progress_callback:
                await progress_callback(0, len(pv_addresses), "Reading from cache...")

            # Get all cached values from Redis (O(1) per value)
            cached_values = await self.redis.get_all_pv_values()
            logger.info(f"Retrieved {len(cached_values)} cached values from Redis")

            # Check cache coverage
            if len(cached_values) == 0:
                logger.warning("Cache is empty, falling back to direct EPICS read")
                return await self.create_snapshot(data, created_by, progress_callback)

            read_time = datetime.now()
            logger.info(f"Cache read completed in {(read_time - start_time).total_seconds():.2f}s")

            # Create snapshot record
            snapshot = Snapshot(
                title=data.title,
                comment=data.comment,
                created_by=created_by
            )
            snapshot = await self.snapshot_repo.create(snapshot)

            # Build snapshot values from cache
            snapshot_values_data = []

            for pv_id, setpoint_addr, readback_addr, config_addr in pv_addresses:
                setpoint_cached = cached_values.get(setpoint_addr) if setpoint_addr else None
                readback_cached = cached_values.get(readback_addr) if readback_addr else None

                # Build setpoint value dict
                setpoint_value = None
                if setpoint_cached and setpoint_cached.get("connected"):
                    setpoint_value = {
                        "value": _sanitize_for_json(setpoint_cached.get("value")),
                        "status": setpoint_cached.get("status"),
                        "severity": setpoint_cached.get("severity"),
                        "timestamp": setpoint_cached.get("timestamp"),
                    }

                # Build readback value dict
                readback_value = None
                if readback_cached and readback_cached.get("connected"):
                    readback_value = {
                        "value": _sanitize_for_json(readback_cached.get("value")),
                        "status": readback_cached.get("status"),
                        "severity": readback_cached.get("severity"),
                        "timestamp": readback_cached.get("timestamp"),
                    }

                snapshot_values_data.append({
                    "pv_id": pv_id,
                    "pv_name": setpoint_addr or readback_addr or "",
                    "setpoint_value": setpoint_value,
                    "readback_value": readback_value,
                    "status": setpoint_cached.get("status") if setpoint_cached else None,
                    "severity": setpoint_cached.get("severity") if setpoint_cached else None,
                    "timestamp": datetime.now(),
                })

            if progress_callback:
                await progress_callback(
                    len(pv_addresses), len(pv_addresses),
                    f"Saving {len(snapshot_values_data)} values to database..."
                )

            # Use fast COPY insert
            count = await self.value_repo.bulk_create_fast(snapshot.id, snapshot_values_data)

            total_time = datetime.now()
            logger.info(f"Snapshot created from cache in {(total_time - start_time).total_seconds():.2f}s "
                       f"({count} values)")

            return SnapshotSummaryDTO(
                id=snapshot.id,
                title=snapshot.title,
                comment=snapshot.comment,
                createdDate=snapshot.created_at,
                createdBy=snapshot.created_by,
                pvCount=count
            )
        except Exception as e:
            logger.exception(f"Error creating snapshot from cache '{data.title}': {e}")
            raise

    async def restore_snapshot(
        self,
        snapshot_id: str,
        request: RestoreRequestDTO | None = None
    ) -> RestoreResultDTO:
        """
        Restore PV values from a snapshot to EPICS.

        This is the critical high-performance path for writes.
        """
        logger.info(f"Restoring snapshot: {snapshot_id}")
        start_time = datetime.now()

        # Get snapshot values
        if request and request.pvIds:
            values = await self.value_repo.get_by_snapshot_and_pvs(
                snapshot_id, request.pvIds
            )
        else:
            values = await self.value_repo.get_by_snapshot(snapshot_id)

        if not values:
            return RestoreResultDTO(
                totalPVs=0,
                successCount=0,
                failureCount=0,
                failures=[]
            )

        # Get PV info for addresses
        pv_ids = [v.pv_id for v in values]
        pvs = await self.pv_repo.get_by_ids(pv_ids)
        pv_map = {pv.id: pv for pv in pvs}

        # Build values to write (only setpoints, not readbacks)
        values_to_write: dict[str, Any] = {}
        pv_id_by_address: dict[str, str] = {}

        for val in values:
            pv = pv_map.get(val.pv_id)
            if not pv or pv.read_only:
                continue
            if pv.setpoint_address and val.setpoint_value:
                write_value = val.setpoint_value.get("value")
                if write_value is not None:
                    values_to_write[pv.setpoint_address] = write_value
                    pv_id_by_address[pv.setpoint_address] = pv.id

        logger.info(f"Writing {len(values_to_write)} PV values")

        # Write to EPICS in parallel
        results = await self.epics.put_many(values_to_write)

        # Process results
        failures = []
        success_count = 0

        for address, (success, error) in results.items():
            if success:
                success_count += 1
            else:
                pv_id = pv_id_by_address.get(address, "")
                failures.append({
                    "pvId": pv_id,
                    "pvName": address,
                    "error": error or "Unknown error"
                })

        total_time = datetime.now()
        logger.info(f"Restore completed in {(total_time - start_time).total_seconds():.2f}s "
                   f"({success_count} success, {len(failures)} failures)")

        return RestoreResultDTO(
            totalPVs=len(values_to_write),
            successCount=success_count,
            failureCount=len(failures),
            failures=failures
        )

    async def compare_snapshots(
        self,
        snapshot1_id: str,
        snapshot2_id: str
    ) -> ComparisonResultDTO:
        """Compare two snapshots and return differences."""
        # Get both snapshots
        snap1 = await self.snapshot_repo.get_with_values(snapshot1_id)
        snap2 = await self.snapshot_repo.get_with_values(snapshot2_id)

        if not snap1 or not snap2:
            raise ValueError("One or both snapshots not found")

        # Build value maps
        values1 = {v.pv_id: v for v in snap1.values}
        values2 = {v.pv_id: v for v in snap2.values}

        # Get PVs for tolerance info
        all_pv_ids = set(values1.keys()) | set(values2.keys())
        pvs = await self.pv_repo.get_by_ids(list(all_pv_ids))
        pv_map = {pv.id: pv for pv in pvs}

        differences = []
        match_count = 0

        for pv_id in all_pv_ids:
            val1 = values1.get(pv_id)
            val2 = values2.get(pv_id)
            pv = pv_map.get(pv_id)

            v1 = val1.setpoint_value.get("value") if val1 and val1.setpoint_value else None
            v2 = val2.setpoint_value.get("value") if val2 and val2.setpoint_value else None

            # Check if within tolerance
            within_tolerance = self._values_within_tolerance(
                v1, v2,
                pv.abs_tolerance if pv else 0,
                pv.rel_tolerance if pv else 0
            )

            if within_tolerance:
                match_count += 1
            else:
                differences.append({
                    "pvId": pv_id,
                    "pvName": val1.pv_name if val1 else (val2.pv_name if val2 else ""),
                    "value1": v1,
                    "value2": v2,
                    "withinTolerance": False
                })

        return ComparisonResultDTO(
            snapshot1Id=snapshot1_id,
            snapshot2Id=snapshot2_id,
            differences=differences,
            matchCount=match_count,
            differenceCount=len(differences)
        )

    def _values_within_tolerance(
        self,
        v1: Any,
        v2: Any,
        abs_tol: float,
        rel_tol: float
    ) -> bool:
        """Check if two values are within tolerance."""
        if v1 is None and v2 is None:
            return True
        if v1 is None or v2 is None:
            return False

        try:
            f1, f2 = float(v1), float(v2)
            diff = abs(f1 - f2)

            # Check absolute tolerance
            if diff <= abs_tol:
                return True

            # Check relative tolerance
            if rel_tol > 0 and f1 != 0:
                if diff / abs(f1) <= rel_tol:
                    return True

            return False
        except (TypeError, ValueError):
            # Non-numeric values: exact match
            return v1 == v2

    async def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot and all its values."""
        return await self.snapshot_repo.delete_with_values(snapshot_id)
