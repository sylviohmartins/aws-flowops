"""Local asynchronous worker facade with durable claims, independent of Streamlit."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock

from flowops.core.engine import Engine
from flowops.domain.models import Execution, Status


class LocalWorker:
    def __init__(
        self,
        engine: Engine,
        workers: int = 4,
        *,
        on_done: Callable[[str], None] | None = None,
    ):
        self.engine = engine
        self.on_done = on_done
        self.pool = ThreadPoolExecutor(
            max_workers=max(1, min(workers, 8)), thread_name_prefix="flowops"
        )
        self.futures: dict[str, Future[Execution]] = {}
        self.lock = Lock()

    def _execute(self, execution_id: str) -> Execution:
        try:
            return self.engine.execute(execution_id)
        finally:
            if self.on_done is not None:
                self.on_done(execution_id)

    def enqueue(self, execution_id: str) -> Future[Execution]:
        with self.lock:
            future = self.futures.get(execution_id)
            if future is None or future.done():
                future = self.pool.submit(self._execute, execution_id)
                self.futures[execution_id] = future
            return future

    def dispatch_pending(self) -> None:
        for execution in self.engine.store.history(2000):
            if execution.status == Status.PENDING:
                self.enqueue(execution.id)

    def close(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=False)
