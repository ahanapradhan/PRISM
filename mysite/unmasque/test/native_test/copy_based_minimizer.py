"""ctid-halving minimizer that materializes every candidate before probing.

This mirrors :class:`ViewMinimizer` step for step.  The only difference is the
probe relation: instead of leaving the candidate half as a view over the dirty
table, it creates a real (unlogged) table, builds PK/FK indexes, runs
``ANALYZE`` so the planner has fresh statistics, and only then executes the query.

The repetition / timing loop lives in ``Minimizer.check_result_for_half``; this
class only overrides how the candidate is built (``_create_candidate``) and
dropped (``_drop_candidate``), reporting materialization, index-build, and ANALYZE time
separately.
"""
from time import perf_counter

from .view_minimizer import ViewMinimizer


class CopyBasedMinimizer(ViewMinimizer):

    def __init__(self, connectionHelper,
                 core_relations, all_sizes,
                 sampling_status,
                 expect_populated=True):
        super().__init__(connectionHelper, core_relations, all_sizes,
                         sampling_status, expect_populated,
                         name="Copy_Minimizer")
        self.plan_costs = []

    def _create_candidate(self, start_ctid, end_ctid, tab, view):
        """Materialize the ctid half, build PK/FK indexes, then refresh statistics."""
        queries = self.connectionHelper.queries
        candidate = self.get_fully_qualified_table_name(view)
        dirty = self.get_fully_qualified_table_name(tab)

        t0 = perf_counter()
        self.connectionHelper.execute_sql(
            [queries.create_table_as_select_star_from_ctid(end_ctid, start_ctid, candidate, dirty)],
            self.logger)
        t1 = perf_counter()
        # Build PK/FK indexes on the materialized candidate (CTAS does not copy indexes).
        try:
            from ...src.util.index_utils import create_pkfk_indexes_on_qualified
            # `tab` is the dirty/backup relation name; base table metadata is keyed by original table name.
            base_table = tab[:-len("_un") ] if tab.endswith("_un") else tab
            index_s = create_pkfk_indexes_on_qualified(self.connectionHelper, candidate, base_table, self.logger)
        except Exception:
            index_s = 0.0
            raise
        t2 = perf_counter()
        self.connectionHelper.execute_sql([queries.analyze_table(candidate)], self.logger)
        t3 = perf_counter()
        self.logger.debug(f"COPY_MATERIALIZED: {candidate} [{start_ctid}, {end_ctid}]")
        return {"create_s": t1 - t0, "index_s": index_s, "analyze_s": t3 - t2}

    def _drop_candidate(self, view):
        self.connectionHelper.execute_sql(
            [self.connectionHelper.queries.drop_table_cascade(
                self.get_fully_qualified_table_name(view))], self.logger)

    def check_result_for_half(self, start_ctid, end_ctid, tab, view, query):
        # A stale relation of the candidate's name (from an aborted probe) must
        # not be there.  Done once, outside the timed/repeated section.
        self.drop_relation_silently(view)
        return super().check_result_for_half(start_ctid, end_ctid, tab, view, query)

    def create_view_execute_app_drop_view(self, end_ctid, mid_ctid1, mid_ctid2,
                                          query, start_ctid, tabname, dirty_tab):
        result = super().create_view_execute_app_drop_view(
            end_ctid, mid_ctid1, mid_ctid2, query, start_ctid, tabname, dirty_tab)
        # The base class drops a view; our probe is a table.  The probe table is
        # already gone, but a stale relation from an aborted probe must not
        # survive into the next halving round.
        self.connectionHelper.execute_sql(
            [self.connectionHelper.queries.drop_view_or_table_cascade(
                self.connectionHelper.config.schema, tabname)], self.logger)
        return result