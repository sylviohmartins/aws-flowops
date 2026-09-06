"""Local asynchronous worker facade with durable claims, independent of Streamlit."""

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Lock, Thread

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
        self.stopping = Event()
        self.dispatcher: Thread | None = None

    def start(self) -> None:
        """Keep durable queued executions moving when another run releases a scope lock."""
        if self.dispatcher is None:
            self.dispatcher = Thread(
                target=self._dispatch_loop, name="flowops-dispatch", daemon=True
            )
            self.dispatcher.start()

    def _dispatch_loop(self) -> None:
        while not self.stopping.wait(0.5):
            try:
                self.dispatch_pending()
            except Exception:
                logging.getLogger("flowops.worker").warning("Pending dispatch failed; retrying when storage is available.")

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

    def close(self, *, wait: bool = True) -> None:
        self.stopping.set()
        if wait and self.dispatcher is not None:
            self.dispatcher.join()
        self.pool.shutdown(wait=wait, cancel_futures=False)
