"""Scheduler for emulated_hue."""
import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

_schedules: dict[int : asyncio.Task] = {}


def _async_scheduler_factory(
    func: Callable[[], Awaitable[None]], interval_ms: int
) -> Awaitable[None]:
    async def scheduler_func():
        while True:
            await asyncio.sleep(interval_ms / 1000)
            await func()

    return scheduler_func()


def _scheduler_factory(func: Callable[[], None], interval_ms: int) -> Awaitable[None]:
    async def scheduler_func():
        while True:
            await asyncio.sleep(interval_ms / 1000)
            func()

    return scheduler_func()


def _is_async_function(
    func: Callable[[Any], None] | Callable[[Any], Awaitable[None]]
) -> bool:
    is_async_gen = inspect.isasyncgenfunction(func)
    is_coro_fn = asyncio.iscoroutinefunction(func)
    return is_async_gen or is_coro_fn


def add_scheduler(
    func: Callable[[], None] | Callable[[], Awaitable[None]], interval_ms: int
) -> int:
    """Add reoccuring task to scheduler."""
    next_id = max(k for k in _schedules) + 1 if _schedules else 1
    if _is_async_function(func):
        task = asyncio.create_task(_async_scheduler_factory(func, interval_ms))
    else:
        task = asyncio.create_task(_scheduler_factory(func, interval_ms))
    _schedules[next_id] = task
    return next_id


def remove_scheduler(id: int) -> None:
    """Remove a scheduler by id."""
    task = _schedules.pop(id, None)
    if task is not None:
        task.cancel()


def remove_all_schedulers() -> None:
    """Remove all schedulers."""
    for task in _schedules.values():
        task.cancel()
    _schedules.clear()


async def async_stop() -> None:
    """Stop all schedulers."""
    remove_all_schedulers()
