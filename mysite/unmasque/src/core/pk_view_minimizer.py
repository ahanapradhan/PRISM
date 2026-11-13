"""PK-range based view minimizer.

Like :class:`ViewMinimizer`, this recursively halves every core table until the
query result would become empty, but the halving is driven by the primary key
range instead of physical ``ctid`` pages:

1. rename the working table to a dirty name (the original table object is
   never modified -- only renamed);
2. read ``min(pk)`` and ``max(pk)`` of the first PK column;
3. repeatedly create a temporary view of the working-table name restricted to
   a half-open PK interval ``[lo, hi)``, run the application query on it and
   drop the view, keeping whichever half still answers the query;
4. materialize the surviving interval with ``Create table ... as select``,
   drop the dirty table, and count the remaining rows.

No statistics are updated, no extra index is built and nothing else touches
the original table: the only DDL used is rename, create/drop view and the
final CTAS materialization, exactly like the ctid-based view minimizer.
"""
import datetime
from decimal import Decimal

from .view_minimizer import ViewMinimizer
from ..util.Log import Log
from ..util.error_handling import UnmasqueError
from ..util.error_codes import ERROR_002


def pk_mid_value(lo, hi):
    """Midpoint strictly inside the half-open interval ``[lo, hi)``."""
    return lo + (hi - lo) // 2


def pk_interval_supported(lo, hi):
    """Whether recursive halving works for this PK value pair.

    Supported: integers, Decimals and dates/datetimes. Everything else
    (strings, uuids, ...) has no well-defined dense midpoint, so the table is
    left untouched.
    """
    if isinstance(lo, datetime.datetime) != isinstance(hi, datetime.datetime):
        return False
    if isinstance(lo, (int, Decimal)) and not isinstance(lo, bool):
        return isinstance(hi, (int, Decimal)) and not isinstance(hi, bool)
    if isinstance(lo, datetime.date):
        return isinstance(hi, datetime.date)
    return False


def pk_next_value(val):
    """Smallest value strictly greater than ``val`` (upper exclusive bound)."""
    if isinstance(val, datetime.datetime):
        return val + datetime.timedelta(microseconds=1)
    if isinstance(val, datetime.date):
        return val + datetime.timedelta(days=1)
    if isinstance(val, Decimal):
        return val + Decimal(1)
    return val + 1


class PKView_Minimizer(ViewMinimizer):
    """View minimizer that halves tables by PK range mid value."""

    def __init__(self, connectionHelper,
                 core_relations, all_sizes,
                 sampling_status,
                 expect_populated=True,
                 pk_dict=None):
        super().__init__(connectionHelper, core_relations, all_sizes,
                         sampling_status, expect_populated=expect_populated)
        self.logger = Log("PK_View_Minimizer", connectionHelper.config.log_level)
        # Optional table -> "pk_col1,pk_col2" map (e.g. the pipeline's
        # global_pk_dict built from pkfkrelations.csv). Used when the working
        # tables carry no declared PK constraint for catalog introspection.
        self.pk_dict = dict(pk_dict) if pk_dict else {}
        self.pk_columns = {}
        self.pk_sources = {}
        self.pk_intervals = {}
        self.halving_rounds = {}

    def reduce_Database_Instance(self, query, cs_pass):
        core_sizes = self.getCoreSizes()
        sorted_relations = self.__get_tables_sorted_by_size(core_sizes)

        for tabname in sorted_relations:
            view_name = self._get_dirty_name(tabname) if cs_pass \
                else self.connectionHelper.queries.get_restore_name(tabname)
            self.connectionHelper.execute_sql([self.connectionHelper.queries.alter_table_rename_to(
                self.get_fully_qualified_table_name(tabname), view_name)])

            halved = self.do_pk_range_halving(core_sizes, query, tabname, view_name)
            if not halved:
                # No usable PK (or non-numeric/date PK): leave the table as it
                # was by renaming it back. Nothing else was touched.
                self.connectionHelper.execute_sql([self.connectionHelper.queries.alter_table_rename_to(
                    self.get_fully_qualified_table_name(view_name), tabname)])

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

    def do_pk_range_halving(self, core_sizes, query, tabname, dirty_tab):
        """Halve ``dirty_tab`` over its PK range; materialize the survivor.

        Returns True when halving happened (dirty table consumed), False when
        the table was skipped and still holds its original name/content.
        """
        col = self.get_pk_column(tabname, dirty_tab)
        if not col:
            return False
        lo, hi = self.connectionHelper.execute_sql_fetchone(
            self.connectionHelper.queries.get_min_max_of_col(
                self.get_fully_qualified_table_name(dirty_tab), col))
        if lo is None or hi is None:
            return False
        if not pk_interval_supported(lo, hi):
            self.logger.info(f"PK column {col} of {tabname} is not numeric/date; skipping PK halving.")
            return False

        hi = pk_next_value(hi)  # half-open interval [lo, hi) covers the whole table
        rounds = 0
        while hi - lo > 1:
            mid = pk_mid_value(lo, hi)
            if self.check_result_for_pk_half(mid, hi, dirty_tab, tabname, col, query):
                lo = mid  # keep the upper half [mid, hi)
            elif self.check_result_for_pk_half(lo, mid, dirty_tab, tabname, col, query):
                hi = mid  # keep the lower half [lo, mid)
            else:
                self.logger.error("Cannot halve anymore..")
                break
            rounds += 1

        core_sizes = self.update_with_remaining_pk_size(core_sizes, lo, hi, tabname, dirty_tab, col)
        self.pk_intervals[tabname] = (lo, hi)
        self.halving_rounds[tabname] = rounds
        return True

    def get_pk_column(self, tabname, existing_name=None):
        """First PK column of ``tabname`` (composite PKs halve on column 1).

        Resolution order:
        1. the ``pk_dict`` map supplied at construction (pkfk CSV data);
        2. primary-key constraint introspection on the catalog.

        ``existing_name`` is the name the table currently carries in the
        catalog (it may have been renamed away from ``tabname``).
        """
        if tabname in self.pk_columns:
            return self.pk_columns[tabname]
        cols = []
        source = None
        pk_csv = self.pk_dict.get(tabname)
        if pk_csv:
            cols = [col.strip() for col in str(pk_csv).split(",") if col.strip()]
            source = "pk_dict"
        if not cols:
            res, _ = self.connectionHelper.execute_sql_fetchall(
                self.connectionHelper.queries.get_pk_columns(
                    self.connectionHelper.config.schema, existing_name or tabname))
            cols = [row[0] for row in res] if res else []
            source = "catalog" if cols else None
        if not cols:
            self.logger.info(f"No primary key found on {tabname}; skipping PK halving.")
            return None
        if len(cols) > 1:
            self.logger.info(f"{tabname} has a composite PK {cols}; halving on {cols[0]}.")
        self.pk_columns[tabname] = cols[0]
        self.pk_sources[tabname] = source
        return cols[0]

    def check_result_for_pk_half(self, lo, hi, tab, view, pk_col, query):
        """Run the app on the ``[lo, hi)`` view; True if the result survives."""
        self.connectionHelper.execute_sql(
            [self.connectionHelper.queries.create_view_as_select_star_where_pk_range(
                self.get_fully_qualified_table_name(view),
                self.get_fully_qualified_table_name(tab), pk_col, lo, hi)],
            self.logger)
        new_result = self.app.doJob(query)
        self.connectionHelper.execute_sql([self.connectionHelper.queries.drop_view(
            self.get_fully_qualified_table_name(view))], self.logger)
        if self.app.isQ_result_nonEmpty_nullfree(new_result):
            return True  # this half works
        return False  # this half does not work

    def update_with_remaining_pk_size(self, core_sizes, lo, hi, tabname, dirty_tab, pk_col):
        self.connectionHelper.execute_sql(
            [self.connectionHelper.queries.create_table_as_select_star_from_pk_range(
                self.get_fully_qualified_table_name(tabname),
                self.get_fully_qualified_table_name(dirty_tab), pk_col, lo, hi),
             self.connectionHelper.queries.drop_table_cascade(
                 self.get_fully_qualified_table_name(dirty_tab))],
            self.logger)
        core_sizes[tabname] = self.connectionHelper.execute_sql_fetchone_0(
            self.connectionHelper.queries.get_row_count(self.get_fully_qualified_table_name(tabname)), self.logger)
        self.logger.debug(f"REMAINING TABLE SIZE {tabname}: {core_sizes[tabname]} "
                          f"(pk [{lo}, {hi}) via {pk_col})")
        return core_sizes

    def __get_tables_sorted_by_size(self, core_sizes):
        sort_by_size = sorted(core_sizes, key=lambda x: core_sizes[x], reverse=True)
        sorted_relations = []
        for tab in sort_by_size:
            if tab in self.core_relations:
                sorted_relations.append(tab)
        return sorted_relations
