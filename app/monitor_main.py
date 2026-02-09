"""
Standalone PV Monitor process entry point.

This decouples the PV monitoring from the API process for better reliability:
- API crash doesn't affect PV monitoring
- PV Monitor crash doesn't take down the API
- Independent scaling and deployment
- Faster API startup (no 8s PV initialization delay)

Run with: python -m app.monitor_main
"""
import uuid
import signal
import asyncio
import logging

from app.config import get_settings
from app.db.session import async_session_maker
from app.services.watchdog import get_watchdog
from app.services.pv_monitor import get_pv_monitor
from app.services.pv_protocol import parse_pv_name
from app.services.epics_service import get_epics_service
from app.services.redis_service import get_redis_service
from app.services.pvaccess_monitor import get_pvaccess_monitor

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()

# Unique instance ID for leader election
INSTANCE_ID = str(uuid.uuid4())[:8]


async def main():
    """
    Main entry point for the standalone PV Monitor process.

    Startup sequence:
    1. Connect to Redis
    2. Attempt to acquire monitor lock (leader election)
    3. Load PV addresses from database
    4. Start PV Monitor with batched initialization
    5. Start Watchdog (if enabled)
    6. Run until shutdown signal

    Shutdown sequence:
    1. Stop Watchdog
    2. Stop PV Monitor
    3. Release monitor lock
    4. Disconnect from Redis
    """
    logger.info(f"Starting Squirrel PV Monitor (instance: {INSTANCE_ID})...")

    # Initialize EPICS service
    epics = get_epics_service()
    logger.info("EPICS service initialized (using aioca)")

    # Connect to Redis
    redis_service = get_redis_service()
    try:
        await redis_service.connect()
        logger.info("Redis service connected")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        logger.error("Redis is required for PV Monitor - exiting")
        return

    # Attempt to acquire leader lock
    # Only one monitor instance should run at a time
    lock_acquired = await redis_service.acquire_monitor_lock(INSTANCE_ID)
    if not lock_acquired:
        logger.warning("Another monitor instance is already running")
        logger.warning("This instance will wait and retry...")

        # Wait for lock to become available
        while not lock_acquired:
            await asyncio.sleep(10)
            lock_acquired = await redis_service.acquire_monitor_lock(INSTANCE_ID)
            if lock_acquired:
                logger.info("Acquired monitor lock - becoming leader")
                break
            else:
                # Check if the current leader is still alive
                current_leader = await redis_service.get_monitor_lock_holder()
                logger.debug(f"Current leader: {current_leader}")
    else:
        logger.info(f"Acquired monitor lock (instance: {INSTANCE_ID})")

    # Start lock renewal task
    lock_renewal_task = asyncio.create_task(_renew_lock_loop(redis_service))

    # Initialize PV Monitor with Redis
    pv_monitor = get_pv_monitor(redis_service)
    pva_monitor = None

    # Load PV addresses from database
    try:
        async with async_session_maker() as session:
            from app.repositories.pv_repository import PVRepository

            pv_repo = PVRepository(session)
            pv_addresses_data = await pv_repo.get_all_addresses()

            # Extract unique addresses (setpoint and readback)
            pv_addresses = set()
            for _, setpoint, readback, config in pv_addresses_data:
                if setpoint:
                    pv_addresses.add(setpoint)
                if readback:
                    pv_addresses.add(readback)

        logger.info(f"Loaded {len(pv_addresses)} unique PV addresses from database")
    except Exception as e:
        logger.error(f"Failed to load PV addresses from database: {e}")
        await redis_service.release_monitor_lock(INSTANCE_ID)
        await redis_service.disconnect()
        return

    # Start PV monitoring (with batched startup)
    # Always start the monitor (for heartbeat) even if no PVs
    ca_pvs: list[str] = []
    pva_pvs: list[str] = []
    for pv_name in pv_addresses:
        protocol, _ = parse_pv_name(pv_name)
        if protocol == "pva":
            pva_pvs.append(pv_name)
        else:
            ca_pvs.append(pv_name)

    if pv_addresses:
        logger.info(
            f"Starting PV Monitor for {len(ca_pvs)} CA addresses and {len(pva_pvs)} PVA addresses "
            f"(batch size: {settings.pv_monitor_batch_size}, "
            f"batch delay: {settings.pv_monitor_batch_delay_ms}ms)"
        )
        await pv_monitor.start(ca_pvs)
        logger.info(f"PV Monitor started for {len(ca_pvs)} CA addresses")

        if pva_pvs:
            pva_monitor = get_pvaccess_monitor(redis_service)
            await pva_monitor.start(pva_pvs)
            logger.info(f"PVAccess Monitor started for {len(pva_pvs)} PVA addresses")
        else:
            logger.info("No PVA addresses found; PVAccess Monitor not started")
    else:
        logger.warning("No PV addresses found in database - starting PV Monitor in idle mode for heartbeat")
        await pv_monitor.start([])  # Start with empty list to initialize heartbeat

    # Start Watchdog if enabled
    watchdog = None
    if settings.watchdog_enabled:
        watchdog = get_watchdog(redis_service, epics, pv_monitor, pva_monitor if pva_pvs else None)
        await watchdog.start()
        logger.info(
            f"Watchdog started (check interval: {settings.watchdog_check_interval}s, "
            f"stale threshold: {settings.watchdog_stale_threshold}s)"
        )
    else:
        logger.info("Watchdog disabled by configuration")

    logger.info("Squirrel PV Monitor startup complete - running until shutdown signal")

    # Wait for shutdown signal
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()

    def handle_signal():
        logger.info("Received shutdown signal")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    await stop_event.wait()

    # Cleanup
    logger.info("Shutting down Squirrel PV Monitor...")

    # Cancel lock renewal
    lock_renewal_task.cancel()
    try:
        await lock_renewal_task
    except asyncio.CancelledError:
        pass

    # Stop Watchdog
    if watchdog and watchdog.is_running():
        await watchdog.stop()
        logger.info("Watchdog stopped")

    # Stop PV Monitor
    if pv_monitor.is_running():
        await pv_monitor.stop()
        logger.info("PV Monitor stopped")

    # Stop PVAccess Monitor
    if pva_monitor and pva_monitor.is_running():
        await pva_monitor.stop()
        logger.info("PVAccess Monitor stopped")

    # Release monitor lock
    await redis_service.release_monitor_lock(INSTANCE_ID)
    logger.info("Released monitor lock")

    # Disconnect Redis
    await redis_service.disconnect()
    logger.info("Redis disconnected")

    # Shutdown EPICS
    await epics.shutdown()
    logger.info("EPICS service shut down")

    logger.info("Squirrel PV Monitor shutdown complete")


async def _renew_lock_loop(redis_service) -> None:
    """
    Continuously renew the monitor lock to maintain leadership.

    Runs every 10 seconds (lock TTL is 30 seconds).
    """
    while True:
        try:
            await asyncio.sleep(10)
            renewed = await redis_service.renew_monitor_lock(INSTANCE_ID)
            if not renewed:
                logger.error("Failed to renew monitor lock - lost leadership")
                # Could trigger graceful shutdown here
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error renewing monitor lock: {e}")


if __name__ == "__main__":
    asyncio.run(main())
