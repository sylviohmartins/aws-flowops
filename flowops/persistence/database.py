"""Small DB-API compatibility layer for SQLite-shaped repository queries on PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, overload


class HybridRow(Mapping[str, Any]):
    """Row supporting both sqlite3.Row-style numeric and named access."""

    def __init__(self, columns: Sequence[str], values: Sequence[Any]):
        self._columns = tuple(columns)
        self._values = tuple(values)
        self._mapping = dict(zip(self._columns, self._values, strict=True))

    @overload
    def __getitem__(self, key: str) -> Any: ...

    @overload
    def __getitem__(self, key: int) -> Any: ...

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._columns)


class PostgresCursor:
    """Expose psycopg cursor results with sqlite3.Row-compatible semantics."""

    def __init__(self, cursor: Any):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)

    def _columns(self) -> tuple[str, ...]:
        description = self._cursor.description or ()
        return tuple(str(getattr(column, "name", column[0])) for column in description)

    def _row(self, values: Sequence[Any] | None) -> HybridRow | None:
        if values is None:
            return None
        return HybridRow(self._columns(), values)

    def fetchone(self) -> HybridRow | None:
        return self._row(self._cursor.fetchone())

    def fetchall(self) -> list[HybridRow]:
        columns = self._columns()
        return [HybridRow(columns, values) for values in self._cursor.fetchall()]

    def __iter__(self) -> Iterator[HybridRow]:
        columns = self._columns()
        for values in self._cursor:
            yield HybridRow(columns, values)


class PostgresConnection:
    """Convert qmark placeholders while keeping repository SQL backend-neutral."""

    def __init__(self, connection: Any):
        self._connection = connection

    @staticmethod
    def translate(sql: str) -> str:
        # FlowOps repository SQL never embeds question marks in string literals.
        return sql.replace("?", "%s")

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> PostgresCursor:
        cursor = self._connection.cursor()
        cursor.execute(self.translate(sql), tuple(parameters))
        return PostgresCursor(cursor)


def is_postgres(database: str) -> bool:
    lowered = database.lower()
    return lowered.startswith("postgres://") or lowered.startswith("postgresql://")
