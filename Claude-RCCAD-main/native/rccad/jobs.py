"""Track asynchronous Studio work across its foreground and background pools."""
from collections import deque
from dataclasses import asdict, dataclass
from itertools import count
import time

from PySide6.QtCore import QObject, QRunnable, Signal

from .kernel import CadError


@dataclass
class Job:
    id: int
    label: str
    pool: str
    priority: int
    revision: int
    progress: float | None = None
    state: str = 'queued'
    discarded: bool = False
    duration_ms: float | None = None


class JobManager:
    def __init__(self, revision):
        self.revision = revision
        self._ids = count(1)
        self.active = {}
        self.completed = deque(maxlen=32)

    def bind(self, name, pool):
        return JobQueue(self, name, pool)

    def report(self):
        return {
            'active': [asdict(job) for job in self.active.values()],
            'recent': [asdict(job) for job in reversed(self.completed)],
        }


class JobQueue:
    def __init__(self, manager, name, pool):
        self.manager = manager
        self.name = name
        self.pool = pool

    def waitForDone(self, timeout=-1):
        return self.pool.waitForDone(timeout)

    def start(self, work, priority=0):
        manager = self.manager
        job = Job(next(manager._ids), work.label, self.name, priority, manager.revision())
        manager.active[job.id] = job
        work.job = job

        def finish(state):
            manager.active.pop(job.id, None)
            job.state = 'discarded' if job.discarded else state
            manager.completed.append(job)

        work.signals.done.connect(lambda _value: finish('completed'))
        work.signals.failed.connect(lambda _error: finish('failed'))
        try:
            self.pool.start(work, priority)
        except Exception:
            finish('failed_to_submit')
            raise


class WorkSignals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)


class Work(QRunnable):
    def __init__(self, function, label='Zadanie w tle'):
        super().__init__()
        self.function = function
        self.label = label
        self.job = None
        self.signals = WorkSignals()
        self.elapsed_ms = None

    def run(self):
        if self.job is not None:
            self.job.state = 'running'
        start = time.perf_counter()
        try:
            try:
                value = self.function()
            finally:
                self.elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
                if self.job is not None:
                    self.job.duration_ms = self.elapsed_ms
        except Exception as exc:
            message = str(exc) if isinstance(exc, CadError) else f'Operacja nie powiodła się: {exc}'
            try:
                self.signals.failed.emit(message)
            except RuntimeError:
                pass        # okno zamknięte, zanim praca w tle się skończyła (np. przygotowanie rozwinięcia)
            return
        try:
            self.signals.done.emit(value)
        except RuntimeError:
            pass
