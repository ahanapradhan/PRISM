from abc import ABC
from time import perf_counter

from ...src.core.abstract.AppExtractorBase import AppExtractorBase
from ...src.core.executables.nullfree_executable import NullFreeExecutable


def mid_ctid_calculate_shortcut(size):
    mid_row = int(size / 2)
    mid_ctid1 = "(" + str(0) + "," + str(mid_row) + ")"
    mid_ctid2 = "(" + str(0) + "," + str(mid_row + 1) + ")"
    return mid_ctid1, mid_ctid2


class Minimizer(AppExtractorBase, ABC):

    def __init__(self, connectionHelper, core_relations, all_sizes, name):
        AppExtractorBase.__init__(self, connectionHelper, name, all_sizes)
        self.core_relations = core_relations
        self.mock = False
        self.all_relations = list(all_sizes.keys())
        self.all_relations.sort()
        self.error_table = None
        # Experiment hooks: one "iteration" is one ctid-halving round.
        # `on_iteration` is called once per iteration (for EXPLAIN cost probes);
        # timings are collected directly in `timing_records` (see below).
        self.iteration = 0
        self.on_iteration = None
        self._iteration_hooked = False
        # Repetition / timing instrumentation.  The first probe of every
        # halving iteration is run `repeats` times and each run is recorded.
        self.repeats = 1
        self._probe_measured = False
        self.timing_records = []

    def getCoreSizes(self):
        sizes = {}
        for table in self.all_relations:
            count = self.connectionHelper.execute_sql_fetchone_0(
                self.connectionHelper.queries.get_row_count(self.get_fully_qualified_table_name(table)))
            if count is not None:
                sizes[table] = count
        self.logger.debug(sizes)
        return sizes

    def extract_params_from_args(self, args):
        return args[0]

    def sanity_check(self, query, expect_populated=True):
        # SANITY CHECK
        if self.app.is_query_result_no_full_nullfree_row(query):
            if expect_populated:
                self.logger.error("Error: Query out of extractable domain\n")
            else:
                self.logger.debug("Falsified OR probe returned no rows, as expected.")
            return False
        return True

    def create_view_execute_app_drop_view(self,
                                          end_ctid,
                                          mid_ctid1,
                                          mid_ctid2,
                                          query,
                                          start_ctid,
                                          tabname,
                                          dirty_tab):
        self.iteration += 1
        self._iteration_hooked = False
        self._probe_measured = False
        self.logger.debug(f"MIN_ITER_START: {self.iteration} {tabname}")
        if isinstance(self.app, NullFreeExecutable):
            end_ctid, start_ctid = self.check_sanity_when_nullfree_exe(end_ctid, mid_ctid1, mid_ctid2, query,
                                                                       start_ctid,
                                                                       tabname, dirty_tab)
        else:
            end_ctid, start_ctid = self.check_sanity_when_base_exe(end_ctid, mid_ctid1, mid_ctid2, query,
                                                                   start_ctid,
                                                                   tabname, dirty_tab)
        self.connectionHelper.execute_sql([self.connectionHelper.queries.drop_view(
                                                    self.get_fully_qualified_table_name(tabname))])
        self.logger.debug(f"MIN_ITER_END: {self.iteration}")
        return end_ctid, start_ctid

    def check_sanity_when_nullfree_exe(self, end_ctid, mid_ctid1, mid_ctid2, query, start_ctid, tabname, dirty_tab):
        if self.check_result_for_half(mid_ctid2, end_ctid, dirty_tab, tabname, query):
            # Take the lower half
            start_ctid = mid_ctid2
        elif self.check_result_for_half(start_ctid, mid_ctid1, dirty_tab, tabname, query):
            # Take the upper half
            end_ctid = mid_ctid1
        else:
            self.logger.error("Cannot halve anymore..")
            start_ctid, end_ctid = None, None
        return end_ctid, start_ctid

    def check_sanity_when_base_exe(self, end_ctid, mid_ctid1, mid_ctid2, query, start_ctid, tabname, dirty_tab):
        if self.check_result_for_half(mid_ctid2, end_ctid, dirty_tab, tabname, query):
            # Take the lower half
            start_ctid = mid_ctid2
        else:
            # Take the upper half
            end_ctid = mid_ctid1
        return end_ctid, start_ctid

    def drop_relation_silently(self, tabname):
        """Drop a stale relation (table or view) of the given name, if any.

        The minimizer renames the working table to a backup/dirty name and
        creates views in its place. A crashed previous run can leave the
        backup name occupied; the rename would then fail silently (DuplicateTable
        is swallowed by cus_execute_sqls) and every later create-view /
        create-table on the working name degrades into a full-size no-op.
        """
        kind = self.connectionHelper.is_view_or_table(tabname, self.connectionHelper.config.schema)
        if kind == 'table':
            fn = self.connectionHelper.queries.drop_table_cascade
        elif kind == 'view':
            fn = self.connectionHelper.queries.drop_view
        else:
            return
        self.connectionHelper.execute_sql(
            [fn(self.get_fully_qualified_table_name(tabname))], self.logger)

    def get_start_and_end_ctids(self, core_sizes, query, tabname, dirty_tab):
        self.drop_relation_silently(dirty_tab)
        self.connectionHelper.execute_sql([self.connectionHelper.queries.alter_table_rename_to(
                                                self.get_fully_qualified_table_name(tabname), dirty_tab)])
        end_ctid, mid_ctid1, mid_ctid2, start_ctid = self.get_mid_ctids(core_sizes, tabname, dirty_tab)

        if mid_ctid1 is None:
            self.connectionHelper.execute_sql([self.connectionHelper.queries.alter_table_rename_to(
                                        self.get_fully_qualified_table_name(dirty_tab), tabname)])
            return None, None

        self.logger.debug(start_ctid, mid_ctid1, mid_ctid2, end_ctid)
        end_ctid, start_ctid = self.create_view_execute_app_drop_view(end_ctid,
                                                                      mid_ctid1,
                                                                      mid_ctid2,
                                                                      query,
                                                                      start_ctid,
                                                                      tabname,
                                                                      dirty_tab)
        return end_ctid, start_ctid

    def get_mid_ctids(self, core_sizes, tabname, dirty_tab):
        start_page, start_row = self.get_boundary("min", dirty_tab)
        end_page, end_row = self.get_boundary("max", dirty_tab)
        start_ctid = "(" + str(start_page) + "," + str(start_row) + ")"
        end_ctid = "(" + str(end_page) + "," + str(end_row) + ")"
        mid_ctid1, mid_ctid2 = mid_ctid_calculate_shortcut(core_sizes[tabname])
        if start_ctid == mid_ctid1:
            mid_ctid1, mid_ctid2 = self.determine_mid_ctid_from_db(dirty_tab)
        return end_ctid, mid_ctid1, mid_ctid2, start_ctid

    def get_boundary(self, min_or_max, tabname):
        m_ctid = self.connectionHelper.execute_sql_fetchone_0(
            self.connectionHelper.queries.get_ctid_from(min_or_max, self.get_fully_qualified_table_name(tabname)))
        m_ctid = m_ctid[1:-1]
        m_ctid2 = m_ctid.split(",")
        row = int(m_ctid2[1])
        page = int(m_ctid2[0])
        return page, row

    def _notify_iteration(self, view, query):
        """Expose the candidate relation once it exists (for cost probes)."""
        if self.on_iteration is not None and not self._iteration_hooked:
            self._iteration_hooked = True
            self.on_iteration(self.iteration, view, query)

    def _create_candidate(self, start_ctid, end_ctid, tab, view):
        """Build the candidate half. Returns the seconds spent per component."""
        queries = self.connectionHelper.queries
        t0 = perf_counter()
        self.connectionHelper.execute_sql(
            [queries.create_view_as_select_star_where_ctid(end_ctid, start_ctid,
                        self.get_fully_qualified_table_name(view), self.get_fully_qualified_table_name(tab))],
            self.logger)
        return {"create_s": perf_counter() - t0, "analyze_s": 0.0}

    def _drop_candidate(self, view):
        self.connectionHelper.execute_sql([self.connectionHelper.queries.drop_view(
                                                    self.get_fully_qualified_table_name(view))], self.logger)

    def check_result_for_half(self, start_ctid, end_ctid, tab, view, query):
        """Probe one ctid half.

        The first probe of an iteration is repeated ``self.repeats`` times
        (create candidate -> run app -> drop candidate each time) and every
        run is stored in ``self.timing_records``.  Any further probe of the
        same iteration runs once and is not recorded.
        """
        measure = not self._probe_measured
        self._probe_measured = True
        reps = max(1, self.repeats) if measure else 1
        works = None
        for rep in range(1, reps + 1):
            parts = self._create_candidate(start_ctid, end_ctid, tab, view)
            if measure and rep == 1:
                self._notify_iteration(view, query)   # untimed EXPLAIN hook

            t0 = perf_counter()
            result = not self.app.is_query_result_no_full_nullfree_row(query)
            exec_s = perf_counter() - t0

            t0 = perf_counter()
            self._drop_candidate(view)
            drop_s = perf_counter() - t0

            if works is None:
                works = result
            elif result != works:
                self.logger.error(f"Probe result changed between repetitions (iteration {self.iteration})")
            if measure:
                record = {"iteration": self.iteration, "table": view, "rep": rep,
                          "create_s": round(parts["create_s"], 4),
                          "analyze_s": round(parts["analyze_s"], 4),
                          "exec_s": round(exec_s, 4),
                          "drop_s": round(drop_s, 4),
                          "with_overhead_s": round(parts["create_s"] + parts["analyze_s"]
                                                   + exec_s + drop_s, 4),
                          "exec_only_s": round(exec_s, 4)}
                self.timing_records.append(record)
                self.logger.debug(f"MIN_TIMING: {record}")
        return works  # this half works / does not work

    def update_with_remaining_size(self, core_sizes, end_ctid, start_ctid, tabname, dirty_tab):
        self.logger.debug(start_ctid, end_ctid)
        self.drop_relation_silently(tabname)
        self.connectionHelper.execute_sql(
            [self.connectionHelper.queries.create_table_as_select_star_from_ctid(end_ctid, start_ctid,
                                                            self.get_fully_qualified_table_name(tabname),
                                                                 self.get_fully_qualified_table_name(dirty_tab)),
             self.connectionHelper.queries.drop_table_cascade(self.get_fully_qualified_table_name(dirty_tab))],
                                                                    self.logger)
        core_sizes[tabname] = self.connectionHelper.execute_sql_fetchone_0(
            self.connectionHelper.queries.get_row_count(self.get_fully_qualified_table_name(tabname)), self.logger)
        self.logger.debug("REMAINING TABLE SIZE", core_sizes[tabname])
        if core_sizes[tabname] == 1:
            res, _ = self.connectionHelper.execute_sql_fetchall(
                                            self.connectionHelper.queries.get_star(
                                                self.get_fully_qualified_table_name(tabname)))
            self.logger.debug(res)
        return core_sizes

    def determine_mid_ctid_from_db(self, tabname):
        count = self.connectionHelper.execute_sql_fetchone_0(
                                            self.connectionHelper.queries.get_row_count(
                                                    self.get_fully_qualified_table_name(tabname)))
        mid_idx = int(count / 2)
        if not mid_idx:
            return None, None
        offset = str(mid_idx - 1)
        mid_ctid1 = self.connectionHelper.execute_sql_fetchone_0(
            self.connectionHelper.queries.select_ctid_from_tabname_offset(
                                                self.get_fully_qualified_table_name(tabname), offset))
        self.logger.debug(mid_ctid1)
        mid_ctid2 = self.connectionHelper.execute_sql_fetchone_0(
            self.connectionHelper.queries.select_next_ctid(self.get_fully_qualified_table_name(tabname), mid_ctid1))
        self.logger.debug(mid_ctid2)
        return mid_ctid1, mid_ctid2

    def doJob(self, *args):
        super().doJob(*args)
        return self.result

    def see_d_min(self, table):
        res, des = self.connectionHelper.execute_sql_fetchall(self.connectionHelper.queries.get_star(
                                                    self.get_fully_qualified_table_name(table)))
        for row in res:
            self.logger.debug(row)

    def restore_d_min(self):
        for tab in self.core_relations:
            drop_fn = self.get_drop_fn(tab)
            self.connectionHelper.execute_sql([self.connectionHelper.queries.create_table_as_select_star_from(
                self.get_fully_qualified_table_name(self.connectionHelper.queries.get_dmin_tabname(tab)),
                                                        self.get_fully_qualified_table_name(tab)),
                drop_fn(tab), self.connectionHelper.queries.alter_table_rename_to(
                    self.get_fully_qualified_table_name(self.connectionHelper.queries.get_dmin_tabname(tab)), tab)])