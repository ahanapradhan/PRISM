"""PK-range based view minimizer.

Halves tables by primary-key value ranges (one view per probe) instead of ctid
ranges. Falls back to ctid halving for tables without known PK columns.
"""
import csv
import pathlib
from decimal import Decimal
from time import perf_counter

from .view_minimizer import ViewMinimizer
from ..util.error_codes import ERROR_002
from ..util.error_handling import UnmasqueError

INT_TYPES = {"smallint", "integer", "bigint"}
TEXT_TYPES = {"character varying", "character", "text", "name"}


class PKViewMinimizer(ViewMinimizer):

    def __init__(self, connectionHelper, core_relations, all_sizes, sampling_status,
                 expect_populated=True, global_pk_dict=None, name="PKView_Minimizer"):
        super().__init__(connectionHelper, core_relations, all_sizes,
                         sampling_status, expect_populated=expect_populated, name=name)
        if global_pk_dict is None:
            global_pk_dict = self._load_pk_dict_from_csv()
        self.pk_columns = {tab: [c.strip() for c in cols.split(",") if c.strip()]
                           for tab, cols in global_pk_dict.items()}

    # ------------------------------------------------------------------ PK info
    def _load_pk_dict_from_csv(self):
        """Mirror of Initiator.__make_pkfk_complete_graph's global_pk_dict logic."""
        cfg = self.connectionHelper.config
        base = pathlib.Path(getattr(cfg, "base_path", "") or "")
        pkfk = getattr(cfg, "pkfk", "pkfkrelations.csv")
        candidates = [
            (base / pkfk).resolve() if str(base) else None,
            (pathlib.Path.cwd() / "mysite" / pkfk).resolve(),
            (pathlib.Path(__file__).resolve().parents[4] / pkfk).resolve(),
        ]
        path = None
        for candidate in candidates:
            if candidate and candidate.exists():
                path = candidate
                break
        pk_dict, seen = {}, []
        if path is None:
            self.logger.info(
                f"pkfk csv not found (tried {[str(c) for c in candidates if c]}); "
                "PK minimizer will fall back to ctid halving")
            return pk_dict
        with open(path, "rt") as f:
            rows = list(csv.reader(f))[1:]
        for row in rows:
            if len(row) < 6:
                continue
            if row[2].upper() == 'Y':
                pk_dict[row[0]] = pk_dict.get(row[0], '') + ("," if row[0] in seen else '') + row[1]
                seen.append(row[0])
        return pk_dict

    # ------------------------------------------------------------------ main loop
    def doActualJob(self, args=None):
        query = self.extract_params_from_args(args)
        if not self.sanity_check(query, self.expect_populated):
            if not self.expect_populated:
                self.logger.info("No disjunct exists; the falsified OR probe returned no rows.")
                return False
            self.logger.error(" Original database is not giving populated result!")
            raise UnmasqueError(ERROR_002, "pk_view_minimizer", "")
        return self.reduce_Database_Instance(query, False)

    def reduce_Database_Instance(self, query, cs_pass):
        core_sizes = self.getCoreSizes()
        sorted_relations = sorted((t for t in core_sizes if t in self.core_relations),
                                  key=lambda t: core_sizes[t], reverse=True)

        for tabname in sorted_relations:
            view_name = self._get_dirty_name(tabname) if cs_pass \
                else self.connectionHelper.queries.get_restore_name(tabname)
            self.drop_relation_silently(view_name)
            self.connectionHelper.execute_sql([self.connectionHelper.queries.alter_table_rename_to(
                self.get_fully_qualified_table_name(tabname), view_name)])

            pk_cols = self.pk_columns.get(tabname)
            if pk_cols:
                core_sizes = self._reduce_table_by_pk(core_sizes, query, tabname, view_name, pk_cols)
            else:
                self.logger.debug(f"No PK known for {tabname}; falling back to ctid halving")
                # Revert rename so the standard ctid-halving flow can manage it.
                self.connectionHelper.execute_sql([self.connectionHelper.queries.alter_table_rename_to(
                    self.get_fully_qualified_table_name(view_name), tabname)])
                view_name = self._get_dirty_name(tabname) if cs_pass \
                    else self.connectionHelper.queries.get_restore_name(tabname)
                self.drop_relation_silently(view_name)
                self.connectionHelper.execute_sql([self.connectionHelper.queries.alter_table_rename_to(
                    self.get_fully_qualified_table_name(tabname), view_name)])
                rctid = self.connectionHelper.execute_sql_fetchone(
                    self.connectionHelper.queries.get_min_max_ctid(
                        self.get_fully_qualified_table_name(view_name)))
                core_sizes = self.do_interPage_viewBased_binary_halving(
                    core_sizes, query, tabname, rctid, view_name)
                core_sizes = self.do_intraPage_copyBased_binary_halving(
                    core_sizes, query, tabname, self._get_dirty_name(tabname))

            if not self.sanity_check(query):
                raise UnmasqueError(ERROR_002, "pk_view_minimizer",
                                    f"Problem occured in Table {tabname}, having size {core_sizes[tabname]}.")

        for tabname in self.core_relations:
            self.connectionHelper.execute_sql(
                [self.connectionHelper.queries.drop_table_cascade(
                    self.connectionHelper.queries.get_dmin_tabname(tabname)),
                 self.connectionHelper.queries.create_table_as_select_star_from(
                     self.connectionHelper.queries.get_dmin_tabname(tabname), tabname)])

        self.populate_dict_info()
        return True

    # ------------------------------------------------------------------ per table
    def _reduce_table_by_pk(self, core_sizes, query, tabname, view_name, pk_cols):
        fq_tab = self.get_fully_qualified_table_name(tabname)
        fq_dirty = self.get_fully_qualified_table_name(view_name)

        pred = "TRUE"
        self._set_view(fq_tab, fq_dirty, pred)

        for col in pk_cols:
            pred = self._halve_on_column(query, fq_tab, fq_dirty, view_name, tabname, col, pred)

        self.connectionHelper.execute_sql([
            self.connectionHelper.queries.drop_view(fq_tab),
            f"CREATE UNLOGGED TABLE {fq_tab} WITH (autovacuum_enabled=false) AS SELECT * FROM {fq_dirty} WHERE {pred};",
            self.connectionHelper.queries.drop_table_cascade(fq_dirty)], self.logger)
        remaining = int(self.connectionHelper.execute_sql_fetchone_0(
            self.connectionHelper.queries.get_row_count(fq_tab), self.logger) or 0)
        if remaining > self.max_row_no:
            self.logger.debug(f"{tabname}: {remaining} rows left after PK halving (non-unique PK values?)")
        core_sizes[tabname] = remaining
        return core_sizes

    @staticmethod
    def _compose_pred(base_pred, col_clauses):
        clauses = [base_pred] if base_pred and base_pred != "TRUE" else []
        clauses.extend([c for c in col_clauses if c])
        return " AND ".join(clauses) if clauses else "TRUE"

    def _halve_on_column(self, query, fq_tab, fq_dirty, dirty_name, tabname, col, pred):
        """Recursively halve the value range of `col` inside `pred`. Returns the new predicate.

        Keeps only the current column's active lower/upper bounds to avoid
        accumulating subsumed predicates in the generated view.
        """
        base_pred = pred if pred and pred != "TRUE" else "TRUE"
        data_type = self._column_type(dirty_name, col)
        is_int = data_type in INT_TYPES
        is_text = data_type in TEXT_TYPES
        ce = f'{col} COLLATE "default"' if is_text else col

        lower_clause = ""
        upper_clause = ""

        def current_pred():
            return self._compose_pred(base_pred, [lower_clause, upper_clause])

        cur = current_pred()
        if is_int:
            lo, hi = self.connectionHelper.execute_sql_fetchone(
                f"SELECT min({ce}), max({ce}) FROM {fq_dirty} WHERE {cur};")
            mid = None
        else:
            lo, hi, mid = self._stats(fq_dirty, ce, cur)

        while lo is not None and lo != hi:
            if is_int:
                mid = (lo + hi) // 2
            elif mid == hi:
                mid = self.connectionHelper.execute_sql_fetchone(
                    f"SELECT max({ce}) FROM {fq_dirty} WHERE {cur} AND {ce} < {self._lit(hi)};")[0]

            left = self._compose_pred(base_pred, [lower_clause, f"{ce} <= {self._lit(mid)}"])
            right = self._compose_pred(base_pred, [f"{ce} > {self._lit(mid)}", upper_clause])

            self.iteration += 1
            self._iteration_hooked = False
            self._probe_measured = False
            self.logger.debug(f"MIN_ITER_START: {self.iteration} {tabname} (pk {col})")
            if self._probe_pk(query, fq_tab, fq_dirty, tabname, left):
                upper_clause = f"{ce} <= {self._lit(mid)}"
                hi = mid if is_int else None
            elif self._probe_pk(query, fq_tab, fq_dirty, tabname, right):
                lower_clause = f"{ce} > {self._lit(mid)}"
                lo = mid + 1 if is_int else None
            else:
                self.logger.error("Cannot halve anymore..")
                self.logger.debug(f"MIN_ITER_END: {self.iteration}")
                break
            self.logger.debug(f"MIN_ITER_END: {self.iteration}")

            cur = current_pred()
            if not is_int:
                lo, hi, mid = self._stats(fq_dirty, ce, cur)

        return current_pred()

    # ------------------------------------------------------------------ instrumented probe
    def _probe_pk(self, query, fq_tab, fq_dirty, tabname, pred):
        """Probe a PK-range predicate with timing/iteration-hook instrumentation.

        The first call within an iteration is measured and repeated according to
        ``self.repeats``; subsequent calls in the same iteration run once without
        recording, matching :meth:`Minimizer.check_result_for_half`.
        """
        measure = not self._probe_measured
        self._probe_measured = True
        reps = max(1, self.repeats) if measure else 1
        works = None
        for rep in range(1, reps + 1):
            t0 = perf_counter()
            self._set_view(fq_tab, fq_dirty, pred)
            create_s = perf_counter() - t0
            if measure and rep == 1:
                self._notify_iteration(tabname, query)

            t0 = perf_counter()
            result = not self.app.is_query_result_no_full_nullfree_row(query)
            exec_s = perf_counter() - t0

            t0 = perf_counter()
            self.connectionHelper.execute_sql(
                [self.connectionHelper.queries.drop_view(fq_tab)], self.logger)
            drop_s = perf_counter() - t0

            if works is None:
                works = result
            elif result != works:
                self.logger.error(
                    f"Probe result changed between repetitions (iteration {self.iteration})")
            if measure:
                record = {
                    "iteration": self.iteration,
                    "table": tabname,
                    "rep": rep,
                    "create_s": round(create_s, 4),
                    "index_s": 0.0,
                    "analyze_s": 0.0,
                    "exec_s": round(exec_s, 4),
                    "drop_s": round(drop_s, 4),
                    "with_overhead_s": round(create_s + exec_s + drop_s, 4),
                    "exec_only_s": round(exec_s, 4),
                }
                self.timing_records.append(record)
                self.logger.debug(f"MIN_TIMING: {record}")
        return works

    # ------------------------------------------------------------------ helpers
    def _stats(self, fq_dirty, ce, pred):
        row = self.connectionHelper.execute_sql_fetchone(
            f"SELECT min({ce}), max({ce}), percentile_disc(0.5) WITHIN GROUP (ORDER BY {ce}) "
            f"FROM {fq_dirty} WHERE {pred};")
        return row[0], row[1], row[2]

    def _column_type(self, table, col):
        row = self.connectionHelper.execute_sql_fetchone(
            "SELECT data_type FROM information_schema.columns "
            f"WHERE table_schema = '{self.connectionHelper.config.schema}' "
            f"AND table_name = '{table}' AND column_name = '{col.lower()}';")
        return row[0] if row else ""

    def _set_view(self, fq_tab, fq_dirty, pred):
        self.connectionHelper.execute_sql([
            self.connectionHelper.queries.drop_view(fq_tab),
            f"CREATE VIEW {fq_tab} AS SELECT * FROM {fq_dirty} WHERE {pred};"], self.logger)

    @staticmethod
    def _lit(v):
        if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"


# Backward-compatible alias
PKView_Minimizer = PKViewMinimizer
