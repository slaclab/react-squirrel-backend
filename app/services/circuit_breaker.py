"""
Circuit Breaker implementation for EPICS access resilience.

Prevents cascading failures when EPICS servers are unresponsive by:
- Tracking failure rates per IOC/server
- Opening circuit when failure threshold exceeded
- Allowing periodic retries in half-open state
- Automatically recovering when service is healthy

Uses aiobreaker library for robust async circuit breaker implementation.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any, Callable, TypeVar

from aiobreaker import CircuitBreaker, CircuitBreakerError, CircuitBreakerListener

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, requests blocked
    HALF_OPEN = "half_open" # Testing if service recovered


@dataclass
class CircuitStats:
    """Statistics for a circuit breaker."""
    name: str
    state: CircuitState
    failure_count: int
    success_count: int
    last_failure: datetime | None
    opened_at: datetime | None
    call_count: int


class CircuitBreakerLogger(CircuitBreakerListener):
    """Listener to log circuit breaker state changes."""

    def state_change(self, cb: CircuitBreaker, old_state, new_state):
        """Called when circuit breaker state changes."""
        logger.warning(
            f"Circuit breaker '{cb.name}' state changed: {old_state} -> {new_state}"
        )

    def failure(self, cb: CircuitBreaker, exc: Exception):
        """Called when a failure is recorded."""
        logger.debug(f"Circuit breaker '{cb.name}' recorded failure: {exc}")

    def success(self, cb: CircuitBreaker):
        """Called when a success is recorded."""
        logger.debug(f"Circuit breaker '{cb.name}' recorded success")


class EpicsCircuitBreakerManager:
    """
    Manages circuit breakers for EPICS IOC connections.

    Each IOC/server can have its own circuit breaker to isolate failures.
    This prevents one failing IOC from blocking access to healthy ones.

    Configuration:
    - fail_max: Number of failures before opening circuit (default: 5)
    - reset_timeout: Seconds before trying again in half-open state (default: 30)
    - exclude: Exceptions that don't count as failures

    Usage:
        manager = EpicsCircuitBreakerManager()

        # Use decorator
        @manager.protect("IOC:LINAC")
        async def read_linac_pv(pv_name):
            return await caget(pv_name)

        # Or use context manager
        async with manager.circuit("IOC:LINAC"):
            value = await caget("LINAC:TEMP")
    """

    def __init__(
        self,
        fail_max: int = 5,
        reset_timeout: float = 30.0,
    ):
        self._circuits: dict[str, CircuitBreaker] = {}
        self._fail_max = fail_max
        self._reset_timeout = reset_timeout
        self._listener = CircuitBreakerLogger()
        self._stats: dict[str, CircuitStats] = {}
        self._lock = asyncio.Lock()

    def get_circuit(self, name: str) -> CircuitBreaker:
        """
        Get or create a circuit breaker for a named resource.

        Args:
            name: Identifier for the resource (e.g., IOC name, server address)

        Returns:
            CircuitBreaker instance for this resource
        """
        if name not in self._circuits:
            cb = CircuitBreaker(
                fail_max=self._fail_max,
                reset_timeout=self._reset_timeout,
                listeners=[self._listener],
                name=name,
            )
            self._circuits[name] = cb
            self._stats[name] = CircuitStats(
                name=name,
                state=CircuitState.CLOSED,
                failure_count=0,
                success_count=0,
                last_failure=None,
                opened_at=None,
                call_count=0,
            )
        return self._circuits[name]

    def protect(self, circuit_name: str):
        """
        Decorator to protect a function with a circuit breaker.

        Usage:
            @manager.protect("IOC:LINAC")
            async def read_value(pv_name):
                return await caget(pv_name)
        """
        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                cb = self.get_circuit(circuit_name)
                try:
                    result = await cb.call_async(func, *args, **kwargs)
                    self._record_success(circuit_name)
                    return result
                except CircuitBreakerError:
                    logger.warning(f"Circuit '{circuit_name}' is OPEN, request rejected")
                    raise
                except Exception as e:
                    self._record_failure(circuit_name, e)
                    raise
            return wrapper
        return decorator

    async def call(
        self,
        circuit_name: str,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Call a function through a circuit breaker.

        Args:
            circuit_name: Name of the circuit breaker to use
            func: Async function to call
            *args, **kwargs: Arguments to pass to the function

        Returns:
            Result from the function

        Raises:
            CircuitBreakerError: If circuit is open
            Exception: If function raises and circuit records failure
        """
        cb = self.get_circuit(circuit_name)
        try:
            result = await cb.call_async(func, *args, **kwargs)
            self._record_success(circuit_name)
            return result
        except CircuitBreakerError:
            logger.warning(f"Circuit '{circuit_name}' is OPEN, request rejected")
            raise
        except Exception as e:
            self._record_failure(circuit_name, e)
            raise

    def is_open(self, circuit_name: str) -> bool:
        """Check if a circuit is open (blocking requests)."""
        if circuit_name not in self._circuits:
            return False
        cb = self._circuits[circuit_name]
        return cb.state.name == "open"

    def is_closed(self, circuit_name: str) -> bool:
        """Check if a circuit is closed (allowing requests)."""
        if circuit_name not in self._circuits:
            return True  # Default to closed if circuit doesn't exist
        cb = self._circuits[circuit_name]
        return cb.state.name == "closed"

    def force_open(self, circuit_name: str) -> None:
        """Force a circuit open (for maintenance/testing)."""
        cb = self.get_circuit(circuit_name)
        cb.open()
        self._update_state(circuit_name, CircuitState.OPEN)
        logger.info(f"Circuit '{circuit_name}' forced OPEN")

    def force_close(self, circuit_name: str) -> None:
        """Force a circuit closed (for recovery)."""
        cb = self.get_circuit(circuit_name)
        cb.close()
        self._update_state(circuit_name, CircuitState.CLOSED)
        logger.info(f"Circuit '{circuit_name}' forced CLOSED")

    def get_stats(self, circuit_name: str) -> CircuitStats | None:
        """Get statistics for a circuit."""
        return self._stats.get(circuit_name)

    def get_all_stats(self) -> list[CircuitStats]:
        """Get statistics for all circuits."""
        # Update states from actual circuit breakers
        for name, cb in self._circuits.items():
            if name in self._stats:
                state_name = cb.state.name
                self._stats[name].state = CircuitState(state_name)
        return list(self._stats.values())

    def get_open_circuits(self) -> list[str]:
        """Get names of all open circuits."""
        return [
            name for name, cb in self._circuits.items()
            if cb.state.name == "open"
        ]

    def _record_success(self, circuit_name: str) -> None:
        """Record a successful call."""
        if circuit_name in self._stats:
            stats = self._stats[circuit_name]
            stats.success_count += 1
            stats.call_count += 1
            # Update state from actual circuit
            if circuit_name in self._circuits:
                stats.state = CircuitState(self._circuits[circuit_name].state.name)

    def _record_failure(self, circuit_name: str, error: Exception) -> None:
        """Record a failed call."""
        if circuit_name in self._stats:
            stats = self._stats[circuit_name]
            stats.failure_count += 1
            stats.call_count += 1
            stats.last_failure = datetime.now()
            # Update state from actual circuit
            if circuit_name in self._circuits:
                cb = self._circuits[circuit_name]
                new_state = CircuitState(cb.state.name)
                if new_state == CircuitState.OPEN and stats.state != CircuitState.OPEN:
                    stats.opened_at = datetime.now()
                stats.state = new_state

    def _update_state(self, circuit_name: str, state: CircuitState) -> None:
        """Update circuit state in stats."""
        if circuit_name in self._stats:
            stats = self._stats[circuit_name]
            if state == CircuitState.OPEN:
                stats.opened_at = datetime.now()
            stats.state = state


# Singleton instance
_manager: EpicsCircuitBreakerManager | None = None


def get_circuit_breaker_manager(
    fail_max: int = 5,
    reset_timeout: float = 30.0
) -> EpicsCircuitBreakerManager:
    """Get or create the circuit breaker manager singleton."""
    global _manager
    if _manager is None:
        _manager = EpicsCircuitBreakerManager(
            fail_max=fail_max,
            reset_timeout=reset_timeout
        )
    return _manager
