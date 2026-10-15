from functools import wraps
from time import perf_counter


def timed(func):
    """Декоратор описывает время работы функции."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        started_at = perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed = perf_counter() - started_at
            print(f'[{func.__name__}] Время работы: {elapsed:.2f} сек')

    return wrapper
