"""Parallel hybrid minimizer (rev 2): race View and Copy probes per iteration.

At every iteration the same logical probe is executed on enabled arms in
parallel (separate DB connections/cores). The first answer wins, the others are
cancelled. Existing halving logic (candidate progression given an outcome,
termination) is reused from the native_test minimizers; racing only replaces
probe execution.

Default: arms = ["view", "copy"] (2 connections) using the ctid-halving driver
(shared by ViewMinimizer/CopyBasedMinimizer). PK is an optional third arm, off
by default. When "pk" is enabled and applicable to the query (all core tables
have known PK columns per PKViewMinimizer mapping), the PK-range halving driver
is used so view/copy/pk all race on the same PK-predicate candidate; if PK is
enabled but not applicable, it is skipped for that run.

Candidate relations are created as TEMP objects (session-local) so concurrent
arms do not collide while shadowing original table names for the query. Scratch
schema ``minim_<run_id>`` is created/cleaned for non-temp objects as needed.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import signal
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional, Set

import psycopg2

from .pk_view_minimizer import PKViewMinimizer
from .copy_based_minimizer import CopyBasedMinimizer  # for type/reference; logic reused
from ...src.util.ConnectionFactory import ConnectionHelperFactory
from ...src.util.PostgresConnectionHelper import PostgresConnectionHelper


class CancelledByRace(Exception):
    """Normal loser-path cancellation; not an error."""


@dataclass
class ArmResult:
    arm: str
    status: str  # won / cancelled / error
    outcome: Optional[bool] = None
    elapsed_s: float = 0.0
    error: Optional[str] = None


@dataclass
class IterLog:
    iter: int
    candidate_size: Any
    winner_arm: str
    outcome: bool
    wall_time_s: float
    arms: Dict[str, ArmResult] = field(default_factory=dict)


def _recover(conn: PostgresConnectionHelper, drop_sqls: List[str], logger=None):
    """Absorb a late stray cancel, then drop attempt objects.

    Arm sessions run in autocommit mode; rollback/commit calls are harmless.
    Leaves the connection usable with no open transaction/held locks.
    """
    raw = getattr(conn, "conn", None)
    if raw is None:
        return
    try:
        raw.rollback()
    except Exception:
        pass
    # absorb a stray cancel that arrived late
    for _ in range(2):
        try:
            cur = raw.cursor()
            try:
                cur.execute("SELECT 1")
            finally:
                cur.close()
            break
        except Exception as e:
            try:
                raw.rollback()
            except Exception:
                pass
            if not _is_cancel(e):
                break
    # drop objects created by this attempt
    for sql in drop_sqls:
        try:
            cur = raw.cursor()
            try:
                cur.execute(sql)
            finally:
                cur.close()
            try:
                raw.commit()
            except Exception:
                pass
        except Exception:
            try:
                raw.rollback()
            except Exception:
                pass
    try:
        raw.rollback()
    except Exception:
        pass


def _is_cancel(exc: BaseException) -> bool:
    # psycopg2.QueryCanceled inherits from DatabaseError/ProgrammingError in some versions;
    # check by name and pgcode 57014.
    name = type(exc).__name__
    if "QueryCanceled" in name or "canceling statement" in str(exc).lower():
        return True
    pgcode = getattr(exc, "pgcode", None)
    return pgcode == "57014"


def _safe_exec(conn: PostgresConnectionHelper, sqls: List[str], logger=None):
    raw = conn.conn
    cur = raw.cursor()
    try:
        for sql in sqls:
            cur.execute(sql)
        raw.commit()
    finally:
        cur.close()


def _exec_fetchone_0(conn: PostgresConnectionHelper, sql: str):
    raw = conn.conn
    cur = raw.cursor()
    try:
        cur.execute(sql)
        row = cur.fetchone()
        raw.commit()
        if row is None:
            return None
        v = row[0]
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
        return v
    finally:
        cur.close()


def _new_connection(config, logger=None) -> PostgresConnectionHelper:
    helper = PostgresConnectionHelper(config)
    helper.connectUsingParams(single_worker=True)
    raw = helper.conn
    # connectUsingParams may have opened an implicit transaction; close it before
    # changing session/autocommit state.
    try:
        raw.commit()
    except Exception:
        try:
            raw.rollback()
        except Exception:
            pass
    # Arm sessions run in autocommit mode so read probes never leave an open
    # transaction holding ACCESS SHARE locks on working-schema tables (which would
    # block main-thread halving DDL such as renames/materializations).
    try:
        raw.autocommit = True
    except Exception:
        pass
    # ensure single-core arm and predictable behavior
    try:
        cur = raw.cursor()
        try:
            cur.execute("SET max_parallel_workers_per_gather = 0;")
            cur.execute("SET max_parallel_workers = 0;")
        finally:
            cur.close()
    except Exception:
        pass
    return helper


class HybridMinimizer(PKViewMinimizer):
    """Per-iteration parallel-race minimizer.

    Default arms: view + copy (2 connections/cores), ctid-halving driver.
    PK is an optional third arm (off by default): enable by passing
    arms=["view","copy","pk"] (or including "pk"). When enabled, PK is used
    only if applicable to the query (all core tables have known PK columns per
    PKViewMinimizer mapping) and the PK-range halving driver is used so all
    raced arms probe the same PK-predicate candidate; otherwise PK is skipped.
    """

    def __init__(self, connectionHelper, core_relations, all_sizes,
                 sampling_status, expect_populated=True, global_pk_dict=None,
                 name="Hybrid_Minimizer", run_id: Optional[str] = None,
                 arms: Optional[List[str]] = None):
        super().__init__(connectionHelper, core_relations, all_sizes,
                         sampling_status, expect_populated=expect_populated,
                         global_pk_dict=global_pk_dict, name=name)
        self.run_id = run_id or uuid.uuid4().hex[:8]
        self.scratch_schema = f"minim_{self.run_id}"
        self.hybrid_logs: List[IterLog] = []
        self._arm_conns: Dict[str, PostgresConnectionHelper] = {}
        self._requested_arms = list(arms) if arms is not None else ["view", "copy"]
        self._arms: List[str] = []
        self._pool: Optional[ThreadPoolExecutor] = None
        self._cancel_event = threading.Event()
        self._in_race = False
        self._wins: Dict[str, int] = {}
        self._total_wall_s: float = 0.0
        self._jsonl_path: Optional[str] = None
        self._old_sigint = None
        self._old_sigterm = None
        self._cleaned = False
        self._outcome_seq: List[tuple] = []  # (iter, outcome, measured)
        self._use_pk_driver = False

    # ------------------------------------------------------------------ arm applicability
    def _pk_applicable_for_run(self) -> bool:
        # PK mapping applicable if every core table has known PK columns.
        for tab in self.core_relations:
            cols = self.pk_columns.get(tab)
            if not cols:
                return False
        return True

    def _determine_arms(self) -> List[str]:
        requested = [a for a in self._requested_arms if a in ("view", "copy", "pk")]
        if not requested:
            requested = ["view", "copy"]
        pk_requested = "pk" in requested
        pk_ok = pk_requested and self._pk_applicable_for_run()
        if pk_ok:
            # Use PK-range halving driver so all arms race on same PK-predicate candidate.
            self._use_pk_driver = True
            arms = [a for a in ["view", "copy", "pk"] if a in requested or a in ("view", "copy", "pk")]
            # ensure deterministic order and include requested ones; keep view,copy,(pk)
            return [a for a in ["view", "copy", "pk"] if a in requested]
        # PK off by default / not requested / not applicable -> ctid-halving driver.
        self._use_pk_driver = False
        arms = [a for a in requested if a != "pk"]
        return arms if arms else ["view", "copy"]

    # ------------------------------------------------------------------ lifecycle
    def _setup_hybrid(self):
        self._arms = self._determine_arms()
        self._wins = {a: 0 for a in self._arms}
        self.hybrid_logs = []
        self._outcome_seq = []
        self._total_wall_s = 0.0
        self._cleaned = False
        # Arm connections are separate DB sessions and must see halving state changes
        # made on the main connection (renames, materializations, etc.), so run main
        # connection in autocommit during the hybrid run.
        self._main_autocommit_prev = None
        try:
            raw = getattr(self.connectionHelper, "conn", None)
            if raw is not None:
                self._main_autocommit_prev = getattr(raw, "autocommit", False)
                try:
                    raw.commit()
                except Exception:
                    try:
                        raw.rollback()
                    except Exception:
                        pass
                raw.autocommit = True
        except Exception:
            self._main_autocommit_prev = None
        # scratch schema for non-temp objects (best-effort isolation/cleanup)
        try:
            self.connectionHelper.execute_sql(
                [f"CREATE SCHEMA IF NOT EXISTS {self.scratch_schema};"], self.logger)
        except Exception:
            try:
                self.connectionHelper.conn.rollback()
            except Exception:
                pass
        # arm connections
        cfg = self.connectionHelper.config
        for arm in self._arms:
            conn = _new_connection(cfg, self.logger)
            # unique application_name for observability/cleanup
            try:
                cur = conn.conn.cursor()
                cur.execute(f"SET application_name = 'hybrid_{self.run_id}_{arm}';")
                conn.conn.commit()
                cur.close()
            except Exception:
                try:
                    conn.conn.rollback()
                except Exception:
                    pass
            self._arm_conns[arm] = conn
        self._pool = ThreadPoolExecutor(max_workers=len(self._arms))
        self._install_signal_handlers()
        self.logger.info(f"Hybrid run {self.run_id}: arms={self._arms}, schema={self.scratch_schema}")

    def _install_signal_handlers(self):
        def handler(signum, frame):
            self.logger.info(f"Hybrid received signal {signum}, cleaning up...")
            try:
                self._cleanup()
            finally:
                # re-raise default behavior
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)

        try:
            self._old_sigint = signal.getsignal(signal.SIGINT)
            self._old_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
        except Exception:
            pass

    def _restore_signal_handlers(self):
        try:
            if self._old_sigint is not None:
                signal.signal(signal.SIGINT, self._old_sigint)
            if self._old_sigterm is not None:
                signal.signal(signal.SIGTERM, self._old_sigterm)
        except Exception:
            pass

    def _cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True
        # cancel running probes and recover
        for arm, conn in list(self._arm_conns.items()):
            try:
                if getattr(conn, "conn", None) is not None:
                    conn.conn.cancel()
            except Exception:
                pass
        # best-effort recover and close
        for arm, conn in list(self._arm_conns.items()):
            try:
                _recover(conn, [], self.logger)
            except Exception:
                pass
            try:
                conn.closeConnection()
            except Exception:
                pass
        self._arm_conns.clear()
        if self._pool is not None:
            try:
                self._pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                try:
                    self._pool.shutdown(wait=False)
                except Exception:
                    pass
            self._pool = None
        # drop scratch schema and any leftover candidate relations created in working schema
        try:
            self.connectionHelper.execute_sql(
                [f"DROP SCHEMA IF EXISTS {self.scratch_schema} CASCADE;"], self.logger)
        except Exception:
            try:
                self.connectionHelper.conn.rollback()
            except Exception:
                pass
        # restore main connection autocommit mode
        try:
            prev = getattr(self, "_main_autocommit_prev", None)
            raw = getattr(self.connectionHelper, "conn", None)
            if prev is not None and raw is not None:
                try:
                    raw.commit()
                except Exception:
                    try:
                        raw.rollback()
                    except Exception:
                        pass
                raw.autocommit = prev
        except Exception:
            pass
        self._restore_signal_handlers()

    # ------------------------------------------------------------------ logging
    def _emit_iter_log(self, log: IterLog, measured: bool = True):
        self.hybrid_logs.append(log)
        self._outcome_seq.append((log.iter, bool(log.outcome), bool(measured)))
        # one-line JSONL/print from main thread only
        arms_status = {a: {"status": r.status, "elapsed_s": round(r.elapsed_s, 4),
                            **({"error": r.error} if r.error else {})}
                       for a, r in log.arms.items()}
        line = {
            "iter": log.iter,
            "candidate_size": log.candidate_size,
            "winner_arm": log.winner_arm,
            "outcome": log.outcome,
            "wall_time_s": round(log.wall_time_s, 4),
            "measured": bool(measured),
            "arms": arms_status,
        }
        msg = json.dumps(line, sort_keys=True, default=str)
        print(msg, flush=True)
        if self._jsonl_path:
            try:
                with open(self._jsonl_path, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass

    def _emit_summary(self):
        final_hash = None
        try:
            # hash of (iteration, outcome) sequence as final result hash
            h = hashlib.sha256()
            h.update(json.dumps(self._outcome_seq, sort_keys=True).encode("utf-8"))
            final_hash = h.hexdigest()[:16]
        except Exception:
            final_hash = None
        summary = {
            "run_id": self.run_id,
            "total_wall_time_s": round(self._total_wall_s, 4),
            "wins_per_arm": dict(self._wins),
            "final_result_hash": final_hash,
            "iterations": len(self._outcome_seq),
        }
        msg = "HYBRID_SUMMARY " + json.dumps(summary, sort_keys=True)
        print(msg, flush=True)
        self.logger.info(msg)
        return summary

    # ------------------------------------------------------------------ doJob wrapper
    def _ensure_main_connection(self):
        """Ensure the main DB connection and app binding are usable for the hybrid run."""
        conn = self.connectionHelper
        if getattr(conn, "conn", None) is None:
            self.logger.warning("Hybrid: main connection missing, reconnecting")
            conn.connectUsingParams()
        raw = conn.conn
        if raw is None:
            raise RuntimeError("Hybrid: unable to establish main database connection")
        try:
            raw.rollback()
        except Exception:
            pass
        try:
            raw.autocommit = True
        except Exception:
            pass
        # ExecutableFactory/app instances can be cached singletons; ensure the
        # minimizer's app is bound to the active main connection helper.
        app = getattr(self, "app", None)
        if app is not None:
            try:
                app.connectionHelper = conn
            except Exception:
                pass
            if getattr(app, "connectionHelper", None) is not conn and getattr(app, "connectionHelper", None) is not None:
                # last resort: replace with a fresh non-singleton executable of same type
                try:
                    cls = type(app)
                    fresh = object.__new__(cls)
                    cls.__init__(fresh, conn)
                    if hasattr(app, "data_schema"):
                        try:
                            fresh.data_schema = getattr(app, "data_schema")
                        except Exception:
                            pass
                    self.app = fresh
                except Exception:
                    pass

    def doActualJob(self, args=None):
        # Default (rev 2): race view+copy on ctid-halving driver. PK is an optional
        # third arm (off by default); when enabled and applicable we use the
        # PK-range halving driver so all arms race on the same PK-predicate candidate.
        self._setup_hybrid()
        try:
            self._ensure_main_connection()
            if not self._use_pk_driver:
                # ctid-halving driver (View/Copy share this search space)
                query = self.extract_params_from_args(args)
                if not self.sanity_check(query, self.expect_populated):
                    if not self.expect_populated:
                        self.logger.info("No disjunct exists; the falsified OR probe returned no rows.")
                        return False
                    self.logger.error(" Original database is not giving populated result!")
                    return False
                result = self.reduce_Database_Instance_ctid(query, False)
            else:
                # PK-halving driver (PKViewMinimizer.doActualJob/reduce logic)
                result = super().doActualJob(args)
            self._emit_summary()
            return result
        finally:
            self._cleanup()

    # ctid driver: same as ViewMinimizer.reduce_Database_Instance but kept explicit
    def reduce_Database_Instance_ctid(self, query, cs_pass):
        core_sizes = self.getCoreSizes()
        sort_by_size = sorted(core_sizes, key=lambda x: core_sizes[x], reverse=True)
        sorted_relations = [tab for tab in sort_by_size if tab in self.core_relations]

        for tabname in sorted_relations:
            view_name = self._get_dirty_name(tabname) if cs_pass \
                else self.connectionHelper.queries.get_restore_name(tabname)
            self.drop_relation_silently(view_name)
            self.connectionHelper.execute_sql([self.connectionHelper.queries.alter_table_rename_to(
                self.get_fully_qualified_table_name(tabname), view_name)])
            rctid = self.connectionHelper.execute_sql_fetchone(
                self.connectionHelper.queries.get_min_max_ctid(self.get_fully_qualified_table_name(view_name)))
            core_sizes = self.do_interPage_viewBased_binary_halving(core_sizes, query, tabname, rctid, view_name)
            core_sizes = self.do_intraPage_copyBased_binary_halving(core_sizes, query, tabname,
                                                                    self._get_dirty_name(tabname))

            if not self.sanity_check(query):
                return False

        for tabname in self.core_relations:
            self.connectionHelper.execute_sql(
                [self.connectionHelper.queries.drop_table_cascade(
                    self.connectionHelper.queries.get_dmin_tabname(tabname)),
                 self.connectionHelper.queries.create_table_as_select_star_from(
                     self.connectionHelper.queries.get_dmin_tabname(tabname), tabname)])

        self.populate_dict_info()
        return True

    # ------------------------------------------------------------------ parallel race core
    def _race(self, candidate_size, probe_fns: Dict[str, Callable[[PostgresConnectionHelper], bool]],
              measured: bool = True):
        """Race arm probe functions; return (outcome, wall_time_s)."""
        # probe_fns: arm -> callable(conn) returning bool outcome (may raise)
        if self._pool is None:
            raise RuntimeError("Hybrid pool not initialized")
        iter_no = self.iteration
        start = perf_counter()
        futs = {}
        for arm, fn in probe_fns.items():
            conn = self._arm_conns[arm]
            futs[self._pool.submit(self._run_probe_wrapper, arm, conn, fn, iter_no)] = arm

        winner_future = None
        pending = set(futs.keys())
        arm_results: Dict[str, ArmResult] = {a: ArmResult(arm=a, status="pending") for a in probe_fns}

        try:
            while pending and winner_future is None:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                # deterministic-ish: iterate in stable order of completion set
                for f in list(done):
                    arm = futs[f]
                    try:
                        res: ArmResult = f.result()
                    except Exception as e:
                        # wrapper should not leak, but be safe
                        arm_results[arm] = ArmResult(arm=arm, status="error", error=str(e))
                        self.logger.error(f"Arm {arm} wrapper error iter {iter_no}: {e}")
                        continue
                    if res.status == "error":
                        arm_results[arm] = res
                        self.logger.error(f"Arm {arm} failed iter {iter_no}: {res.error}")
                        continue
                    if res.status == "cancelled":
                        arm_results[arm] = res
                        continue
                    # success/outcome
                    if winner_future is None:
                        winner_future = f
                        res.status = "won"
                        arm_results[arm] = res
                        break
                    else:
                        # finished at same moment but we already have winner; treat as late
                        res.status = "cancelled"
                        arm_results[arm] = res

            if winner_future is None:
                wall = perf_counter() - start
                self._total_wall_s += wall
                # all arms failed/errored
                raise RuntimeError(f"all arms failed at iteration {iter_no}: "
                                   + "; ".join(f"{a}:{r.error}" for a, r in arm_results.items()))

            outcome = arm_results[futs[winner_future]].outcome

            # cancel losers
            for f in list(pending):
                arm = futs[f]
                try:
                    self._arm_conns[arm].conn.cancel()
                except Exception:
                    pass
            # wait for pending to finish (losers return quickly after cancel)
            if pending:
                done2, still = wait(pending)
                for f in done2:
                    arm = futs[f]
                    try:
                        res = f.result()
                    except Exception as e:
                        res = ArmResult(arm=arm, status="error", error=str(e))
                    # if it succeeded despite cancel, prefer not to override winner; mark cancelled
                    if res.status == "won":
                        res.status = "cancelled"
                    if arm_results[arm].status == "pending":
                        arm_results[arm] = res
                for f in still:
                    arm = futs[f]
                    arm_results[arm] = ArmResult(arm=arm, status="error", error="did not return after cancel")

            wall = perf_counter() - start
            self._total_wall_s += wall
            winner_arm = futs[winner_future]
            self._wins[winner_arm] = self._wins.get(winner_arm, 0) + 1
            # fill any pending (shouldn't happen) as cancelled
            for a, r in arm_results.items():
                if r.status == "pending":
                    r.status = "cancelled"
            # safety: ensure no arm session holds locks/open tx before main-thread DDL
            for arm in probe_fns:
                try:
                    _recover(self._arm_conns[arm], [], self.logger)
                except Exception:
                    pass
            log = IterLog(iter=iter_no, candidate_size=candidate_size,
                          winner_arm=winner_arm, outcome=bool(outcome),
                          wall_time_s=wall, arms=arm_results)
            self._emit_iter_log(log, measured=measured)
            return bool(outcome), wall
        except Exception:
            # best-effort: cancel and drain on unexpected failure
            for f in (pending if 'pending' in locals() else []):
                arm = futs.get(f)
                if arm and arm in self._arm_conns:
                    try:
                        self._arm_conns[arm].conn.cancel()
                    except Exception:
                        pass
            raise

    def _run_probe_wrapper(self, arm: str, conn: PostgresConnectionHelper,
                           fn: Callable[[PostgresConnectionHelper], bool], iter_no: int) -> ArmResult:
        t0 = perf_counter()
        try:
            outcome = fn(conn)
            return ArmResult(arm=arm, status="won", outcome=bool(outcome),
                             elapsed_s=perf_counter() - t0)
        except CancelledByRace:
            return ArmResult(arm=arm, status="cancelled", elapsed_s=perf_counter() - t0)
        except Exception as e:
            if _is_cancel(e):
                return ArmResult(arm=arm, status="cancelled", elapsed_s=perf_counter() - t0)
            return ArmResult(arm=arm, status="error", elapsed_s=perf_counter() - t0,
                             error=str(e))

    # ------------------------------------------------------------------ probe implementations (ctid candidates)
    # Arms create TEMP objects so each session gets its own candidate under the
    # same logical name (query references original table names) without colliding
    # across concurrent connections. pg_temp shadows the working-schema table.
    def _ctid_probe_view(self, conn: PostgresConnectionHelper, start_ctid, end_ctid,
                         dirty_fq: str, candidate_name: str, query: str) -> bool:
        drop_sqls = [f"DROP VIEW IF EXISTS pg_temp.{candidate_name} CASCADE;"]
        try:
            cur = conn.conn.cursor()
            try:
                cur.execute(f"DROP VIEW IF EXISTS pg_temp.{candidate_name} CASCADE;")
                cur.execute(
                    f"CREATE TEMP VIEW {candidate_name} AS SELECT * FROM {dirty_fq} "
                    f"WHERE ctid >= '{start_ctid}' AND ctid <= '{end_ctid}';")
                conn.conn.commit()
            finally:
                cur.close()
            outcome = self._execute_query_for_outcome(conn, query)
            return outcome
        except Exception as e:
            if _is_cancel(e):
                raise CancelledByRace()
            raise
        finally:
            _recover(conn, drop_sqls, self.logger)

    def _ctid_probe_copy(self, conn: PostgresConnectionHelper, start_ctid, end_ctid,
                         dirty_fq: str, candidate_name: str,
                         base_table: str, query: str) -> bool:
        drop_sqls = [f"DROP TABLE IF EXISTS pg_temp.{candidate_name} CASCADE;"]
        try:
            cur = conn.conn.cursor()
            try:
                cur.execute(f"DROP TABLE IF EXISTS pg_temp.{candidate_name} CASCADE;")
                # materialize (one transaction). TEMP table created and read on same connection.
                cur.execute(
                    f"CREATE TEMP TABLE {candidate_name} AS SELECT * FROM {dirty_fq} "
                    f"WHERE ctid >= '{start_ctid}' AND ctid <= '{end_ctid}';")
                conn.conn.commit()
            finally:
                cur.close()
            # build PK/FK indexes (best-effort on temp table)
            try:
                from ...src.util.index_utils import index_specs_for_table
                specs = index_specs_for_table(conn.config, base_table)
                if specs:
                    cur = conn.conn.cursor()
                    try:
                        for suffix, cols, _is_pk in specs:
                            col_list = ", ".join(cols)
                            idx_name = f"{candidate_name}_{suffix}_idx"
                            cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON pg_temp.{candidate_name} ({col_list});")
                        conn.conn.commit()
                    finally:
                        cur.close()
            except Exception:
                try:
                    conn.conn.rollback()
                except Exception:
                    pass
                # index build failure is not fatal for correctness; re-raise to surface issues
                raise
            # ANALYZE as a separate statement afterwards
            cur = conn.conn.cursor()
            try:
                cur.execute(f"ANALYZE pg_temp.{candidate_name};")
                conn.conn.commit()
            finally:
                cur.close()
            outcome = self._execute_query_for_outcome(conn, query)
            return outcome
        except Exception as e:
            if _is_cancel(e):
                raise CancelledByRace()
            raise
        finally:
            _recover(conn, drop_sqls, self.logger)

    # ------------------------------------------------------------------ probe implementations (pk predicate candidates)
    def _pred_probe_view(self, conn: PostgresConnectionHelper, candidate_name: str, fq_dirty: str,
                         pred: str, query: str) -> bool:
        drop_sqls = [f"DROP VIEW IF EXISTS pg_temp.{candidate_name} CASCADE;"]
        try:
            cur = conn.conn.cursor()
            try:
                cur.execute(f"DROP VIEW IF EXISTS pg_temp.{candidate_name} CASCADE;")
                cur.execute(f"CREATE TEMP VIEW {candidate_name} AS SELECT * FROM {fq_dirty} WHERE {pred};")
                conn.conn.commit()
            finally:
                cur.close()
            outcome = self._execute_query_for_outcome(conn, query)
            return outcome
        except Exception as e:
            if _is_cancel(e):
                raise CancelledByRace()
            raise
        finally:
            _recover(conn, drop_sqls, self.logger)

    def _pred_probe_copy(self, conn: PostgresConnectionHelper, candidate_name: str, fq_dirty: str,
                         pred: str, base_table: str, query: str) -> bool:
        drop_sqls = [f"DROP TABLE IF EXISTS pg_temp.{candidate_name} CASCADE;"]
        try:
            cur = conn.conn.cursor()
            try:
                cur.execute(f"DROP TABLE IF EXISTS pg_temp.{candidate_name} CASCADE;")
                cur.execute(f"CREATE TEMP TABLE {candidate_name} AS SELECT * FROM {fq_dirty} WHERE {pred};")
                conn.conn.commit()
            finally:
                cur.close()
            try:
                from ...src.util.index_utils import index_specs_for_table
                specs = index_specs_for_table(conn.config, base_table)
                if specs:
                    cur = conn.conn.cursor()
                    try:
                        for suffix, cols, _is_pk in specs:
                            col_list = ", ".join(cols)
                            idx_name = f"{candidate_name}_{suffix}_idx"
                            cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON pg_temp.{candidate_name} ({col_list});")
                        conn.conn.commit()
                    finally:
                        cur.close()
            except Exception:
                try:
                    conn.conn.rollback()
                except Exception:
                    pass
                raise
            # ANALYZE as a separate statement afterwards
            cur = conn.conn.cursor()
            try:
                cur.execute(f"ANALYZE pg_temp.{candidate_name};")
                conn.conn.commit()
            finally:
                cur.close()
            outcome = self._execute_query_for_outcome(conn, query)
            return outcome
        except Exception as e:
            if _is_cancel(e):
                raise CancelledByRace()
            raise
        finally:
            _recover(conn, drop_sqls, self.logger)

    # ------------------------------------------------------------------ query execution / outcome
    def _execute_query_for_outcome(self, conn: PostgresConnectionHelper, query: str) -> bool:
        """Return True if query gives a populated result (same semantics as app probe).

        Evaluates using the same app/executable logic as sequential minimizers, but
        against the given arm connection (which has its own TEMP candidate).
        """
        # Ensure pg_temp shadows working-schema tables for this session/query.
        try:
            schema = self.connectionHelper.config.schema
            cur = conn.conn.cursor()
            try:
                cur.execute(f"SET search_path=pg_temp,'{schema}';")
                conn.conn.commit()
            finally:
                cur.close()
        except Exception:
            try:
                conn.conn.rollback()
            except Exception:
                pass

        app = getattr(self, 'app', None)
        if app is not None:
            # Use a same-type app bound to the arm connection so probe semantics
            # (wrapping, limits, null/empty interpretation) match exactly.
            # IMPORTANT: executables are per-class singletons in this codebase; do not
            # construct via type(app)(conn) or mutate the shared instance. Create a
            # throwaway non-singleton instance bound to the arm connection instead.
            try:
                cls = type(app)
                arm_app = object.__new__(cls)
                cls.__init__(arm_app, conn)
            except Exception:
                arm_app = None
            if arm_app is not None:
                # copy relevant execution attributes when present
                for attr in ("data_schema",):
                    if hasattr(app, attr):
                        try:
                            setattr(arm_app, attr, getattr(app, attr))
                        except Exception:
                            pass
                try:
                    outcome = not arm_app.is_query_result_no_full_nullfree_row(query)
                    # Release ACCESS SHARE locks on working-schema tables held by this tx.
                    try:
                        conn.conn.rollback()
                    except Exception:
                        pass
                    return outcome
                except Exception as e:
                    if _is_cancel(e):
                        raise
                    # fall through to conservative direct check

        # Fallback: run a limited probe and treat any row as populated.
        q = query.strip().rstrip(';')
        schema = self.connectionHelper.config.schema
        sql = f"SET search_path=pg_temp,'{schema}'; SELECT * FROM ({q}) AS q LIMIT 2;"
        cur = conn.conn.cursor()
        try:
            cur.execute(sql)
            res = cur.fetchall()
            conn.conn.commit()
        finally:
            cur.close()
        # Ensure no open tx/locks remain.
        try:
            conn.conn.rollback()
        except Exception:
            pass
        return len(res) > 0

    # ------------------------------------------------------------------ ctid halving integration (race replaces probe)
    def check_result_for_half(self, start_ctid, end_ctid, tab, view, query):
        """Probe one ctid half by racing arms (replaces sequential probe)."""
        self._iteration_hooked = False
        measure = not self._probe_measured
        self._probe_measured = True
        # candidate relation in working schema uses same naming as existing minimizers
        # so the query (referencing original table name `view`) resolves correctly.
        schema = self.connectionHelper.config.schema
        candidate_fq = f"{schema}.{view}"
        dirty_fq = f"{schema}.{tab}"
        # `view` is the original/logical table name used as candidate; `tab` is the dirty source.
        base_table = view

        # candidate size for logging: estimate rows in ctid range if cheap, else range string
        candidate_size = f"[{start_ctid},{end_ctid}]"

        # iteration hook (untimed EXPLAIN/cost) once per iteration, like base
        if measure and self.on_iteration is not None and not self._iteration_hooked:
            # need candidate to exist for EXPLAIN in view mode? _notify_iteration in base
            # is called after creating candidate for rep==1; here we call hook before race
            # with best-effort: create a temp view on main conn for cost probe then drop.
            try:
                self._iteration_hooked = True
                self.connectionHelper.execute_sql([
                    f"DROP VIEW IF EXISTS {candidate_fq};",
                    f"CREATE VIEW {candidate_fq} AS SELECT * FROM {dirty_fq} WHERE ctid >= '{start_ctid}' AND ctid <= '{end_ctid}';"
                ], self.logger)
                self.on_iteration(self.iteration, view, query)
            except Exception:
                try:
                    self.connectionHelper.conn.rollback()
                except Exception:
                    pass
            finally:
                try:
                    self.connectionHelper.execute_sql([f"DROP VIEW IF EXISTS {candidate_fq};"], self.logger)
                except Exception:
                    try:
                        self.connectionHelper.conn.rollback()
                    except Exception:
                        pass

        probe_fns = {}
        for arm in self._arms:
            if arm == "view" or arm == "pk":
                # view-based ctid probe
                probe_fns[arm] = lambda c, s=start_ctid, e=end_ctid, d=dirty_fq, cn=view, q=query: \
                    self._ctid_probe_view(c, s, e, d, cn, q)
            elif arm == "copy":
                probe_fns[arm] = lambda c, s=start_ctid, e=end_ctid, d=dirty_fq, cn=view, b=base_table, q=query: \
                    self._ctid_probe_copy(c, s, e, d, cn, b, q)

        outcome, wall = self._race(candidate_size, probe_fns, measured=measure)

        if measure:
            # record timing in compatible format for experiment harness
            record = {"iteration": self.iteration, "table": view, "rep": 1,
                      "create_s": 0.0, "index_s": 0.0, "analyze_s": 0.0,
                      "exec_s": round(wall, 4), "drop_s": 0.0,
                      "with_overhead_s": round(wall, 4),
                      "exec_only_s": round(wall, 4)}
            self.timing_records.append(record)
        return outcome

    # ------------------------------------------------------------------ PK halving integration (race replaces probe)
    def _probe_pk(self, query, fq_tab, fq_dirty, tabname, pred):
        """Probe a PK-range predicate by racing arms."""
        measure = not self._probe_measured
        self._probe_measured = True
        candidate_size = pred
        base_table = tabname

        if measure and self.on_iteration is not None and not self._iteration_hooked:
            try:
                self._iteration_hooked = True
                self._set_view(fq_tab, fq_dirty, pred)
                self.on_iteration(self.iteration, tabname, query)
            except Exception:
                try:
                    self.connectionHelper.conn.rollback()
                except Exception:
                    pass
            finally:
                try:
                    self.connectionHelper.execute_sql(
                        [self.connectionHelper.queries.drop_view(fq_tab)], self.logger)
                except Exception:
                    try:
                        self.connectionHelper.conn.rollback()
                    except Exception:
                        pass

        probe_fns = {}
        for arm in self._arms:
            if arm in ("view", "pk"):
                probe_fns[arm] = lambda c, cn=tabname, fd=fq_dirty, p=pred, q=query: \
                    self._pred_probe_view(c, cn, fd, p, q)
            elif arm == "copy":
                probe_fns[arm] = lambda c, cn=tabname, fd=fq_dirty, p=pred, b=base_table, q=query: \
                    self._pred_probe_copy(c, cn, fd, p, b, q)

        outcome, wall = self._race(candidate_size, probe_fns, measured=measure)

        if measure:
            record = {"iteration": self.iteration, "table": tabname, "rep": 1,
                      "create_s": 0.0, "index_s": 0.0, "analyze_s": 0.0,
                      "exec_s": round(wall, 4), "drop_s": 0.0,
                      "with_overhead_s": round(wall, 4),
                      "exec_only_s": round(wall, 4)}
            self.timing_records.append(record)
        return outcome
