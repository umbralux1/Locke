import asyncio
from contextlib import suppress

from loguru import logger

_running_tasks = set()


async def run_processing_tasks(n, *coros):
    semaphore = asyncio.Semaphore(n)

    async def sem_coro(coro):
        try:
            async with semaphore:
                return await coro
        except asyncio.CancelledError:
            coro.close()

    tasks = []

    for coro in coros:
        task = asyncio.create_task(sem_coro(coro))
        _running_tasks.add(task)
        task.add_done_callback(_running_tasks.discard)
        tasks.append(task)

    # logger.info(f"RUN {len(tasks)} processing tasks... with semaphore {n}")
    results = []

    for task in tasks:
        with suppress(asyncio.CancelledError):
            results.append(await task)

    return results


def cancel_processing_tasks():
    if _running_tasks:
        ...
        # logger.info(f"CANCEL {len(_running_tasks)} processing tasks...")

    for t in _running_tasks:
        if t == asyncio.current_task():
            continue

        t.cancel()
