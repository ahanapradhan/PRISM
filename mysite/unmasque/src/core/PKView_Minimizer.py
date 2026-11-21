"""
PKView_Minimizer
================
Same idea as ViewMinimizer (shrink every core table by recursive halving, one
view per trial), but the halving cut is a PRIMARY KEY value range instead of a
ctid range.

Rules this class follows:
  * PK columns come from pkfkrelations.csv (same parsing as Initiator, i.e. the
    content of global_pk_dict).
  * Nothing is done to the original (user-schema) tables, and no ANALYZE / extra
    index / any other physical operation is done on the working tables either.
    The only things created are VIEWs over the (renamed) working table, and, at
    the very end of a table, the one-time materialisation of the final rows.
  * Textual PK columns are compared and sorted with the database default
    collation (COLLATE "default"), so the cut point is consistent with the
    comparisons issued in the view predicates.
  * Composite PKs: halve on the first column until it is a single value, then
    on the second column inside it, and so on.
  * Tables without a PK entry fall back to the inherited ctid halving.

Place next to ViewMinimizer.py (mysite/unmasque/src/core/).
"""
import csv
import pathlib
from decimal import Decimal

from .view_minimizer import ViewMinimizer
from ..util.error_codes import ERROR_002
from ..util.error_handling import UnmasqueError

INT_TYPES = {"smallint", "integer", "bigint"}
TEXT_TYPES = {"character varying", "character", "text", "name"}


class PKView_Minimizer(ViewMinimizer):

    def __init__(self, connectionHelper, core_relations, all_sizes, sampling_status,
                 global_pk_dict=None):
        super().__init__(connectionHelper, core_relations, all_sizes, sampling_status)
        self.name = "PKView_Minimizer"
        if global_pk_dict is None:
            global_pk_dict = self._load_pk_dict_from_csv()
        # {"lineitem": "l_orderkey,l_linenumber"} -> {"lineitem": ["l_orderkey", "l_linenumber"]}
        self.pk_columns = {tab: [c.strip() for c in cols.split(",") if c.strip()]
                           for tab, cols in global_pk_dict.items()}

    # ------------------------------------------------------------------ PK info
    def _load_pk_dict_from_csv(self):
        """Mirror of Initiator.__make_pkfk_complete_graph's global_pk_dict logic."""
        cfg = self.connectionHelper.config
        base = pathlib.Path(cfg.base_path)
        path = (base / cfg.pkfk).resolve()
        pk_dict, seen = {}, []
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
    def reduce_Database_Instance(self, query, cs_pass):
        core_sizes = self.getCoreSizes()
        sorted_relations = sorted((t for t in core_sizes if t in self.core_relations),
                                  key=lambda t: core_sizes[t], reverse=True)

        for tabname in sorted_relations:
            view_name = self._get_dirty_name(tabname) if cs_pass \
                else self.connectionHelper.queries.get_restore_name(tabname)
            self.connectionHelper.execute_sql([self.connectionHelper.queries.alter_table_rename_to(
                self.get_fully_qualified_table_name(tabname), view_name)])

            pk_cols = self.pk_columns.get(tabname)
            if pk_cols:
                core_sizes = self._reduce_table_by_pk(core_sizes, query, tabname, view_name, pk_cols)
            else:
                self.logger.debug(f"No PK known for {tabname}; falling back to ctid halving")
                rctid = self.connectionHelper.execute_sql_fetchone(
                    self.connectionHelper.queries.get_min_max_ctid(
                        self.get_fully_qualified_table_name(view_name)))
                core_sizes = self.do_interPage_viewBased_binary_halving(core_sizes, query, tabname,
                                                                        rctid, view_name)
                core_sizes = self.do_intraPage_copyBased_binary_halving(core_sizes, query, tabname,
                                                                        self._get_dirty_name(tabname))

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
        self._set_view(fq_tab, fq_dirty, pred)  # full view, so the app sees the table

        for col in pk_cols:
            pred = self._halve_on_column(query, fq_tab, fq_dirty, view_name, col, pred)

        # Final rows -> real table under the original name, then drop the dirty
        # table (same end state as Minimizer.update_with_remaining_size).
        self.connectionHelper.execute_sql([
            f"DROP VIEW IF EXISTS {fq_tab} CASCADE;",
            f"CREATE TABLE {fq_tab} AS SELECT * FROM {fq_dirty} WHERE {pred};",
            f"DROP TABLE IF EXISTS {fq_dirty} CASCADE;"])
        remaining = int(self.connectionHelper.execute_sql_fetchone_0(
            self.connectionHelper.queries.get_row_count(fq_tab)))
        if remaining > self.max_row_no:
            self.logger.debug(f"{tabname}: {remaining} rows left after PK halving (non-unique PK values?)")
        core_sizes[tabname] = remaining
        return core_sizes

    def _halve_on_column(self, query, fq_tab, fq_dirty, dirty_name, col, pred):
        """Recursively halve the value range of `col` inside `pred`. Returns the new predicate."""
        data_type = self._column_type(dirty_name, col)
        is_int = data_type in INT_TYPES
        is_text = data_type in TEXT_TYPES
        ce = f'{col} COLLATE "default"' if is_text else col   # default collation for text PKs

        if is_int:   # one min/max query, then pure arithmetic
            lo, hi = self.connectionHelper.execute_sql_fetchone(
                f"SELECT min({ce}), max({ce}) FROM {fq_dirty} WHERE {pred};")
            mid = None
        else:        # dates, decimals, text: take a real median value from the data
            lo, hi, mid = self._stats(fq_dirty, ce, pred)

        while lo is not None and lo != hi:
            if is_int:
                mid = (lo + hi) // 2
            elif mid == hi:      # heavy duplicates at the top: cut just below max
                mid = self.connectionHelper.execute_sql_fetchone(
                    f"SELECT max({ce}) FROM {fq_dirty} WHERE {pred} AND {ce} < {self._lit(hi)};")[0]

            left = f"{pred} AND {ce} <= {self._lit(mid)}"
            right = f"{pred} AND {ce} > {self._lit(mid)}"

            if self._try(query, fq_tab, fq_dirty, left):
                pred = left
                hi = mid if is_int else None
            elif self._try(query, fq_tab, fq_dirty, right):
                pred = right
                lo = mid + 1 if is_int else None
            else:
                break        # both halves needed: this column cannot shrink further

            if not is_int:
                lo, hi, mid = self._stats(fq_dirty, ce, pred)
        return pred

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
            f"DROP VIEW IF EXISTS {fq_tab} CASCADE;",
            f"CREATE VIEW {fq_tab} AS SELECT * FROM {fq_dirty} WHERE {pred};"])

    def _try(self, query, fq_tab, fq_dirty, pred):
        """Same acceptance test the ctid halving uses (Minimizer.check_result_for_half)."""
        self._set_view(fq_tab, fq_dirty, pred)
        result = self.app.doJob(query)
        return bool(self.app.isQ_result_nonEmpty_nullfree(result))

    @staticmethod
    def _lit(v):
        if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"