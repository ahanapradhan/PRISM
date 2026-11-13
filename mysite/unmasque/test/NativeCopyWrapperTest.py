"""Unit tests for the Python wrapper around the native ``pgcopy`` helper.

These tests do not need PostgreSQL or a real ``pgcopy`` binary. They exercise
availability detection and output validation, including the requirement that a
failed index build must not turn a successful table copy into a failure.
"""

from __future__ import annotations

import os
import stat
import sys
from types import SimpleNamespace

import pytest

from mysite.unmasque.src.util import native_copy
from mysite.unmasque.src.util.native_copy import (
    NativeCopyError,
    native_copy_available,
    parse_native_output,
    run_native_copy,
)


def _config():
    return SimpleNamespace(
        host="localhost",
        port="5432",
        dbname="tpch",
        user="postgres",
        password="postgres",
    )


def _fake_binary(tmp_path, output: str, exit_code: int = 0) -> str:
    script = tmp_path / "fake_pgcopy"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if '--help' in sys.argv:\n"
        "    sys.exit(0)\n"
        f"sys.stdout.write({output!r})\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def test_parser_reports_copy_success_and_index_failure_separately():
    output = (
        "PLAN\tlarge=1\tsmall=0\tthreshold=100000\tmax_threads=4\tindex_threads=4\tserial=0\n"
        "RESULT\t1\tlarge\tlineitem\t0.250\t3\t1\t\n"
        "INDEX_RESULT\t1\tlineitem\t0.050\t0\tcould not create index\n"
        "COPY_SECONDS\t0.250\n"
        "INDEX_SECONDS\t0.050\n"
        "TOTAL_SECONDS\t0.300\n"
        "FAILURES\t0\n"
        "INDEX_FAILURES\t1\n"
    )

    parsed = parse_native_output(output)

    assert parsed.failures == 0
    assert parsed.tables["lineitem"].ok
    assert parsed.tables["lineitem"].copied == 3
    assert len(parsed.index_failures) == 1
    assert parsed.index_failures[0].table == "lineitem"
    assert not parsed.index_failures[0].ok


def test_native_copy_keeps_table_when_index_build_fails(tmp_path, monkeypatch):
    output = (
        "PLAN\tlarge=1\tsmall=0\tthreshold=100000\tmax_threads=4\tindex_threads=4\tserial=0\n"
        "RESULT\t1\tlarge\tlineitem\t0.250\t3\t1\t\n"
        "INDEX_RESULT\t1\tlineitem\t0.050\t0\tcould not create index\n"
        "COPY_SECONDS\t0.250\n"
        "INDEX_SECONDS\t0.050\n"
        "TOTAL_SECONDS\t0.300\n"
        "FAILURES\t0\n"
        "INDEX_FAILURES\t1\n"
    )
    monkeypatch.setenv("PRISM_NATIVE_PGCOPY", _fake_binary(tmp_path, output))
    monkeypatch.delenv("PRISM_NATIVE_COPY", raising=False)

    result = run_native_copy(
        _config(),
        source_schema="fresh",
        dest_schema="unmasque",
        tables=["lineitem"],
    )

    assert result.tables["lineitem"].ok
    assert result.failures == 0
    assert len(result.index_failures) == 1


def test_native_copy_raises_when_a_table_copy_fails(tmp_path, monkeypatch):
    output = (
        "RESULT\t1\tlarge\tlineitem\t0.250\t0\t0\tcould not copy rows\n"
        "COPY_SECONDS\t0.250\n"
        "INDEX_SECONDS\t0.000\n"
        "TOTAL_SECONDS\t0.250\n"
        "FAILURES\t1\n"
        "INDEX_FAILURES\t0\n"
    )
    monkeypatch.setenv(
        "PRISM_NATIVE_PGCOPY", _fake_binary(tmp_path, output, exit_code=1)
    )
    monkeypatch.delenv("PRISM_NATIVE_COPY", raising=False)

    with pytest.raises(NativeCopyError, match="lineitem"):
        run_native_copy(
            _config(),
            source_schema="fresh",
            dest_schema="unmasque",
            tables=["lineitem"],
        )


def test_native_copy_can_be_disabled_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISM_NATIVE_PGCOPY", _fake_binary(tmp_path, ""))
    monkeypatch.setenv("PRISM_NATIVE_COPY", "off")

    assert native_copy_available(_config()) is False


def test_missing_binary_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISM_NATIVE_PGCOPY", str(tmp_path / "does-not-exist"))
    monkeypatch.delenv("PRISM_NATIVE_COPY", raising=False)

    assert native_copy_available(_config()) is False


def test_mock_connection_config_stays_on_python_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISM_NATIVE_PGCOPY", _fake_binary(tmp_path, ""))
    monkeypatch.delenv("PRISM_NATIVE_COPY", raising=False)

    # A test/mock config lacks libpq connection fields. Native must not be used
    # even though the binary is runnable.
    mock_config = SimpleNamespace(user_schema="fresh", schema="unmasque")
    assert native_copy_available(mock_config) is False


def test_fake_binary_is_detected_as_available(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISM_NATIVE_PGCOPY", _fake_binary(tmp_path, ""))
    monkeypatch.delenv("PRISM_NATIVE_COPY", raising=False)

    assert native_copy_available(_config()) is True
