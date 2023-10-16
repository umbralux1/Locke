import asyncio
import contextlib
from functools import partial
from threading import Thread, current_thread
from multiprocessing import Pipe, current_process
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from loguru import logger

WORKER_PROCS = 30
WORKER_THREADS = 10


def _proc_initializer():
    proc = current_process()
    logger.info(f"Initialize {proc.name}")

    proc.loop = asyncio.new_event_loop()
    proc.loop.slow_callback_duration = 0.800
    proc.loop_runner = Thread(target=proc.loop.run_forever, daemon=True)
    proc.loop_runner.start()
    logger.info(f"{proc.name} started event loop")

    proc.thread_executor = ThreadPoolExecutor(max_workers=WORKER_THREADS)
    logger.info(f"{proc.name} created pool with {WORKER_THREADS} threads")


_proc_executor = ProcessPoolExecutor(
    max_workers=WORKER_PROCS, initializer=_proc_initializer
)


def _run_in_thread(coro):
    proc = current_process()
    thread = current_thread()
    # logger.info(f'{proc.name}:{thread.name} received task')

    ft = asyncio.run_coroutine_threadsafe(coro(), loop=proc.loop)

    return ft.result()


def _run_coro(coro, task_conn):
    proc = current_process()

    async def wrapper():
        # Notify the process the task has been started:
        task_conn.send(True)

        thread = current_thread()
        # logger.info(f'{proc.name}:{thread.name} started task')

        return await coro()

    return wrapper


def _run_in_process(coro):
    proc = current_process()
    # logger.info(f'{proc.name} received task')

    proc_conn, task_conn = Pipe()

    coro = _run_coro(coro, task_conn)
    ft = proc.loop.run_in_executor(proc.thread_executor, _run_in_thread, coro)

    # Waiting for thread to accept the task:
    proc_conn.recv()

    def task_done_callback(ft):
        task = {"task_id": str(coro)}

        try:
            task["result"] = ft.result()
        except Exception as e:
            task["exception"] = e
            logger.exception(f"{proc.name} failed processing task {coro}")
        finally:
            task_conn.send(task)
            # logger.info(f'{proc.name} finished task')

    ft.add_done_callback(task_done_callback)

    return proc_conn


# _loop = asyncio.get_running_loop()


async def submit(coro, *args, wait_executor=None, **kwargs):
    _loop = asyncio.get_running_loop()
    _loop.slow_callback_duration = 0.800

    coro = partial(coro, *args, **kwargs)
    task_pipe = await _loop.run_in_executor(_proc_executor, _run_in_process, coro)

    waiter = wait_executor or ThreadPoolExecutor(max_workers=1)
    task = await _loop.run_in_executor(waiter, task_pipe.recv)

    with contextlib.suppress(KeyError):
        raise task["exception"]
    return task["result"]
