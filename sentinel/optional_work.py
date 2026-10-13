"""Nonblocking admission for one 8 GiB optional-model reservation at a time."""
import threading


class OptionalModelBudget:
    reserved_rss_bytes=8*1024**3

    def __init__(self): self._gate=threading.Lock()

    def run(self, kind: str, operation, unavailable):
        if kind not in ('url','paired','harm'): raise ValueError('Unknown optional model kind')
        if not self._gate.acquire(blocking=False): return unavailable()
        try: return operation()
        finally: self._gate.release()
