"""Python wrapper around the native ``pgcopy`` backup/restore helper.

The native helper (``mysite/unmasque/native/pgcopy``) is a standalone libpq +
pthreads executable. Python keeps ownership of planning (which tables to copy,
row counts, predicates) and delegates the actual table copies to it.

All production callers must use this module's availability check first so that
PRISM keeps working when the binary cannot be built or executed:

    if native_copy_available(config):
        run_native_copy(...)
    else:
        ... existing Python copy path ...

Environment variables
---------------------
``PRISM_NATIVE_PGCOPY``
    Path to the helper. Defaults to ``mysite/unmasque/native/pgcopy``.
``PRISM_NATIVE_COPY``
    ``off``/``0``/``no``/``false`` disables native copies even when the binary
    is runnable. Any other value (default) leaves the availability check in
    charge.
``PRISM_NATIVE_THRESHOLD``
    Large-table cutoff in rows (default ``100000``).
``PRISM_NATIVE_THREADS``
    Maximum large-table workers (default: up to 4, based on ``os.cpu_count()``).
``PRISM_NATIVE_INDEX_THREADS``
    Maximum concurrent index builds (same default as copy workers).
``PRISM_NATIVE_TIMEOUT``
    Optional subprocess timeout in seconds.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

DEFAULT_BINARY = Path(__file__).resolve().parents[2] / "native" / "pgcopy"
DEFAULT_THRESHOLD = 100_000

_DISABLED_VALUES = {"0", "off", "no", "false", "disabled", "none"}


class NativeCopyError(RuntimeError):
    """Raised when the native helper is unavailable or a table copy fails."""


@dataclass
class TableCopyResult:
    worker: int
    kind: str
    table: str
    seconds: float
    copied: int
    ok: bool
    error: str = ""


@dataclass
class IndexBuildResult:
    worker: int
    table: str
    seconds: float
    ok: bool
    error: str = ""


@dataclass
class NativeCopyResult:
    plan: dict[str, str] = field(default_factory=dict)
    tables: dict[str, TableCopyResult] = field(default_factory=dict)
    indexes: list[IndexBuildResult] = field(default_factory=list)
    copy_seconds: float = 0.0
    index_seconds: float = 0.0
    total_seconds: float = 0.0
    failures: int = 0
    index_failures: list[IndexBuildResult] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""

    def table_order(self) -> list[str]:
        return list(self.tables)


def binary_path() -> Path:
    override = os.environ.get("PRISM_NATIVE_PGCOPY")
    return Path(override).expanduser() if override else DEFAULT_BINARY


def native_copy_requested() -> bool:
    value = os.environ.get("PRISM_NATIVE_COPY", "").strip().lower()
    return value not in _DISABLED_VALUES


def _config_value(config, name):
    value = getattr(config, name, None)
    return None if value is None else str(value)


def _has_connection_config(config) -> bool:
    if config is None:
        return False
    required = ("dbname", "user", "password", "host", "port")
    return all(_config_value(config, name) is not None for name in required)


def native_copy_available(config=None) -> bool:
    """Return True when the native helper can be executed for this config.

    ``config`` is optional: when supplied, the database connection settings are
    validated too. This keeps mock/test connection helpers on the Python path
    even on machines where ``pgcopy`` happens to be built.
    """
    if not native_copy_requested():
        return False
    if config is not None and not _has_connection_config(config):
        return False

    path = binary_path()
    if not path.is_file() or not os.access(path, os.X_OK):
        return False

    try:
        completed = subprocess.run(
            [str(path), "--help"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _conninfo_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def build_conninfo(config) -> str:
    """Build a libpq conninfo string with correctly quoted values."""
    parts = []
    for key in ("host", "port", "dbname", "user", "password"):
        value = _config_value(config, key)
        if value is not None:
            parts.append(f"{key}={_conninfo_value(value)}")
    return " ".join(parts)


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def default_threads() -> int:
    default = max(1, min(4, os.cpu_count() or 1))
    return _positive_int(os.environ.get("PRISM_NATIVE_THREADS"), default)


def default_index_threads() -> int:
    default = default_threads()
    return _positive_int(os.environ.get("PRISM_NATIVE_INDEX_THREADS"), default)


def default_threshold() -> int:
    return _positive_int(os.environ.get("PRISM_NATIVE_THRESHOLD"), DEFAULT_THRESHOLD)


def _timeout():
    raw = os.environ.get("PRISM_NATIVE_TIMEOUT")
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_native_output(stdout: str) -> NativeCopyResult:
    """Parse the machine-readable lines printed by ``pgcopy``.

    Index failures are collected separately. They intentionally do not raise:
    the source relation is allowed to have no usable index definition.
    """
    result = NativeCopyResult(stdout=stdout)
    for raw_line in stdout.splitlines():
        if not raw_line:
            continue
        fields = raw_line.split("\t")
        tag = fields[0]

        if tag == "PLAN":
            for item in fields[1:]:
                key, _, value = item.partition("=")
                if key:
                    result.plan[key] = value
        elif tag == "RESULT" and len(fields) >= 7:
            table = TableCopyResult(
                worker=_parse_int(fields[1]),
                kind=fields[2],
                table=fields[3],
                seconds=_parse_float(fields[4]),
                copied=_parse_int(fields[5]),
                ok=_parse_int(fields[6]) == 1,
                error="\t".join(fields[7:]),
            )
            result.tables[table.table] = table
        elif tag == "INDEX_RESULT" and len(fields) >= 5:
            index = IndexBuildResult(
                worker=_parse_int(fields[1]),
                table=fields[2],
                seconds=_parse_float(fields[3]),
                ok=_parse_int(fields[4]) == 1,
                error="\t".join(fields[5:]),
            )
            result.indexes.append(index)
            if not index.ok:
                result.index_failures.append(index)
        elif tag == "COPY_SECONDS":
            result.copy_seconds = _parse_float(fields[1])
        elif tag == "INDEX_SECONDS":
            result.index_seconds = _parse_float(fields[1])
        elif tag == "TOTAL_SECONDS":
            result.total_seconds = _parse_float(fields[1])
        elif tag == "FAILURES":
            result.failures = _parse_int(fields[1])
        elif tag == "INDEX_FAILURES":
            if not result.index_failures:
                # Older helpers only print the count, not individual results.
                result.index_failures = [
                    IndexBuildResult(-1, "", 0.0, False, "index build failed")
                    for _ in range(_parse_int(fields[1]))
                ]
    return result


def _validate(result: NativeCopyResult, tables: Iterable[str]) -> None:
    expected = list(tables)
    missing = [table for table in expected if table not in result.tables]
    failed = [item for item in result.tables.values() if not item.ok]

    if result.failures == 0 and not failed and not missing:
        return

    details = []
    for item in failed:
        details.append(f"{item.table}: {item.error or 'copy failed'}")
    for table in missing:
        details.append(f"{table}: no RESULT line")
    if not details:
        details.append(f"{result.failures} copy failure(s)")
    raise NativeCopyError("; ".join(details))


def _where_arguments(wheres: Mapping[str, str] | None) -> list[str]:
    args: list[str] = []
    for table, where in (wheres or {}).items():
        if where is None:
            continue
        predicate = str(where).strip()
        if predicate:
            args.extend(["--where", f"{table}={predicate}"])
    return args


def _rows_argument(rows: Mapping[str, int] | None) -> str | None:
    if not rows:
        return None
    entries = []
    for table, value in rows.items():
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count >= 0:
            entries.append(f"{table}:{count}")
    return ",".join(entries) if entries else None


def run_native_copy(
    config,
    *,
    source_schema: str,
    dest_schema: str,
    tables: Iterable[str],
    sql: str = "like_insert",
    rows: Mapping[str, int] | None = None,
    wheres: Mapping[str, str] | None = None,
    threshold: int | None = None,
    max_threads: int | None = None,
    index_threads: int | None = None,
    verify: bool = True,
    serial: bool = False,
    mode: str = "copy",
    logger=None,
) -> NativeCopyResult:
    """Run the native helper and return its parsed result.

    Raises :class:`NativeCopyError` when the helper is unavailable or any table
    copy fails. Index build failures are reported through
    ``result.index_failures`` and are *not* treated as failures.
    """
    table_list = [str(table) for table in tables]
    if not table_list:
        return NativeCopyResult()

    if sql not in {"like_insert", "ctas"}:
        raise ValueError(f"unknown native copy sql shape: {sql!r}")

    if not native_copy_available(config):
        raise NativeCopyError(
            f"native copy helper is not available at {binary_path()}"
        )

    command = [
        str(binary_path()),
        "--conninfo",
        build_conninfo(config),
        "--source",
        str(source_schema),
        "--dest",
        str(dest_schema),
        "--tables",
        ",".join(table_list),
        "--sql",
        sql,
        "--mode",
        mode,
        "--threshold",
        str(default_threshold() if threshold is None else int(threshold)),
        "--max-threads",
        str(default_threads() if max_threads is None else int(max_threads)),
        "--index-threads",
        str(default_index_threads() if index_threads is None else int(index_threads)),
    ]
    command.extend(_where_arguments(wheres))

    rows_arg = _rows_argument(rows)
    if rows_arg:
        command.extend(["--rows", rows_arg])
    if not verify:
        command.append("--no-verify")
    if serial:
        command.append("--serial")

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_timeout(),
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise NativeCopyError(f"native copy timed out: {error}") from error
    except OSError as error:
        raise NativeCopyError(f"could not execute native copy: {error}") from error

    result = parse_native_output(completed.stdout or "")
    result.stderr = completed.stderr or ""

    try:
        _validate(result, table_list)
    except NativeCopyError:
        if completed.returncode != 0 and completed.stderr:
            raise NativeCopyError(
                f"{completed.stderr.strip()} (exit {completed.returncode})"
            ) from None
        raise

    if completed.returncode != 0 and not result.tables:
        raise NativeCopyError(
            completed.stderr.strip() or f"native helper exited {completed.returncode}"
        )

    if logger is not None:
        logger.debug(
            "native copy %s -> %s: %d table(s), copy=%.3fs index=%.3fs total=%.3fs",
            source_schema,
            dest_schema,
            len(result.tables),
            result.copy_seconds,
            result.index_seconds,
            result.total_seconds,
        )
        for index in result.index_failures:
            logger.info(
                "native index build failed for %s (copy kept): %s",
                index.table,
                index.error or "unknown error",
            )

    return result
