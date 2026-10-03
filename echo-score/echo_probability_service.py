"""Bounded, nonblocking delivery of tuning projections to the OCR task."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from types import SimpleNamespace

from echo_probability import calculate_tuning_probability, validate_tuning_input


@dataclass(frozen=True)
class ProjectionState:
    status: str
    result: object = None
    reason: str = ''


class TuningProbabilityService:
    """One running computation, no request queue, and at most 64 cached items.

    Call request from the OCR task only. Superseded work may finish and enter
    the cache, but its result is never returned for a different input. The
    newest request is scheduled at the next tick once the worker is free.
    """

    def __init__(self, calculate=calculate_tuning_probability):
        self._calculate = calculate
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='echo-probability')
        self._pending = None
        self._cache = OrderedDict()
        self._closed = False

    def request(self, template_name, cost, main_rows, sub_rows, target_score):
        if self._closed:
            return ProjectionState('closed')
        if error := validate_tuning_input(template_name, cost, main_rows, sub_rows, target_score):
            return ProjectionState('invalid', reason=error)
        # Snapshot mutable OCR objects before handing them to a worker.
        def snapshot(rows):
            return tuple((r.stat_name, float(r.value), getattr(r, 'value_text', None)) for r in rows)
        main, sub = snapshot(main_rows), snapshot(sub_rows)
        key = (template_name, cost, main, sub, str(target_score))
        if self._pending is not None and self._pending[1].done():
            completed_key, future = self._pending
            self._pending = None
            try:
                state = ProjectionState('ready', result=future.result())
            except Exception:
                state = ProjectionState('error', reason='概率计算失败，请切换声骸或重启功能')
            self._cache[completed_key] = state
            self._cache.move_to_end(completed_key)
            while len(self._cache) > 64:
                self._cache.popitem(last=False)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        if self._pending is None:
            def restore(rows):
                return tuple(SimpleNamespace(stat_name=name, value=value, value_text=text)
                             for name, value, text in rows)
            future = self._executor.submit(self._calculate, template_name, cost,
                                           restore(main), restore(sub), target_score)
            self._pending = (key, future)
        return ProjectionState('pending')

    def close(self):
        if not self._closed:
            self._closed = True
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._cache.clear()
