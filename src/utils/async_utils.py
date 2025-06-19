import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor

# Single shared executor for all decorated functions
_THREAD_POOL = ThreadPoolExecutor()


def force_async(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(_THREAD_POOL, fn, *args, **kwargs)

    return wrapper


def force_sync(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        result = fn(*args, **kwargs)
        return asyncio.get_event_loop().run_until_complete(result) if asyncio.iscoroutine(result) else result

    return wrapper
