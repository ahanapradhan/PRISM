import ast
import copy
import random
from datetime import date, timedelta
from typing import Union

from frozenlist._frozenlist import FrozenList

from .MutationPipeLineBase import MutationPipeLineBase
from ..dataclass.genPipeline_context import GenPipelineContext
from ...util.constants import NON_TEXT_TYPES
from ...util.utils import get_unused_dummy_val, get_dummy_val_for, get_format, get_char, get_escape_string
from ....src.core.abstract.abstractConnection import AbstractConnectionHelper


def generate_random_date(lb, ub):
    start_date = lb
    end_date = ub
    # Generate two random dates
    random_date1 = start_date + timedelta(days=random.randint(0, (end_date - start_date).days))
    return random_date1


def get_boundary_value(v_cand, is_ub):
    if isinstance(v_cand, list) or isinstance(v_cand, tuple):
        v_val = v_cand[-1] if is_ub else v_cand[0]
        if isinstance(v_val, tuple):
            v_val = v_val[-1] if is_ub else v_val[0]
    else:
        v_val = v_cand
    return v_val


class GenerationPipeLineBase(MutationPipeLineBase):

    def __init__(self, connectionHelper: AbstractConnectionHelper, name: str, genCtx: GenPipelineContext):
        super().__init__(connectionHelper, genCtx.core_relations, genCtx.global_min_instance_dict, name)
        self._gen_ctx = genCtx
        self.global_all_attribs = genCtx.global_all_attribs
        self.global_attrib_types = genCtx.global_attrib_types
        self.global_join_graph = genCtx.global_join_graph
        self.global_filter_predicates = genCtx.arithmetic_filters
        self.filter_attrib_dict = genCtx.filter_attrib_dict
        self.attrib_types_dict = genCtx.attrib_types_dict
        self.joined_attribs = genCtx.joined_attribs
        self.filter_in_predicates = genCtx.filter_in_predicates
        self.get_datatype = genCtx.get_datatype  # method
        # B13: CNF route awareness (guarded; defaults to legacy behavior when absent)
        self.cnf = getattr(genCtx, 'cnf', None)
        self.cnf_route = getattr(genCtx, 'cnf_route', None)
        self.cnf_pin_values = copy.deepcopy(getattr(genCtx, 'cnf_pin_values', {}) or {})

    def extract_params_from_args(self, args):
        return args[0]

    def doActualJob(self, args=None) -> bool:
        query = self.extract_params_from_args(args)
        self.do_init()
        check = self.doExtractJob(query)
        return check

    def restore_d_min_from_dict(self) -> None:
        for tab in self.core_relations:
            values = self.global_min_instance_dict[tab]
            attribs, vals = values[0], values[1]
            for i in range(len(attribs)):
                attrib, val = attribs[i], vals[i]
                self.update_with_val(attrib, tab, val)

    def do_init(self) -> None:
        for tab in self.core_relations:
            self.connectionHelper.execute_sql(
                [self.connectionHelper.queries.create_table_as_select_star_from_limit_1(
                    self.get_fully_qualified_table_name(f"{tab}__temp"), self.get_original_table_name(tab)),
                    self.connectionHelper.queries.drop_table(self.get_fully_qualified_table_name(tab)),
                    self.connectionHelper.queries.alter_table_rename_to(
                        self.get_fully_qualified_table_name(f"{tab}__temp"), tab)])
        self.restore_d_min_from_dict()
        self.see_d_min()

    def get_s_val_for_textType(self, attrib_inner, tabname_inner) -> str:
        filtered_val = self.filter_attrib_dict[(tabname_inner, attrib_inner)]
        if isinstance(filtered_val, FrozenList):
            filtered_val = filtered_val[0]
        return filtered_val

    def insert_attrib_vals_into_table(self, att_order, attrib_list_inner,
                                      insert_rows, tabname_inner, insert_logger=True) -> None:
        esc_string = get_escape_string(attrib_list_inner)
        insert_query = self.connectionHelper.queries.insert_into_tab_attribs_format(att_order, esc_string,
                                                                                    self.get_fully_qualified_table_name(
                                                                                        tabname_inner))
        if insert_logger:
            self.connectionHelper.execute_sql_with_params(insert_query, insert_rows, self.logger)
        else:
            self.connectionHelper.execute_sql_with_params(insert_query, insert_rows)

    def update_attrib_in_table(self, attrib, value, tabname) -> None:
        update_query = self.connectionHelper.queries.update_tab_attrib_with_value(
            self.get_fully_qualified_table_name(tabname), attrib, value)
        self.connectionHelper.execute_sql([update_query])

    def doExtractJob(self, query: str) -> bool:
        return True

    def get_other_attribs_in_eqJoin_grp(self, attrib: str) -> list:
        other_attribs = []
        for join_edge in self.global_join_graph:
            if attrib in join_edge:
                other_attribs = copy.deepcopy(join_edge)
                other_attribs.remove(attrib)
                break
        return other_attribs

    def update_attribs_bulk(self, join_tabnames, other_attribs, val) -> None:
        join_tabnames.clear()
        for other_attrib in other_attribs:
            join_tabname = self.find_tabname_for_given_attrib(other_attrib)
            join_tabnames.append(join_tabname)
            self.update_with_val(other_attrib, join_tabname, val)

    def update_attrib_to_see_impact(self, attrib: str, tabname: str):
        prev = self.connectionHelper.execute_sql_fetchone_0(
            self.connectionHelper.queries.select_attribs_from_relation([attrib], tabname))
        val = self.get_different_s_val(attrib, tabname, prev)
        self.logger.debug(f"update {tabname}.{attrib} with value {val} that had previous value {prev}")
        self.update_with_val(attrib, tabname, val)
        return val, prev

    def update_with_val(self, attrib: str, tabname: str, val) -> None:
        if val == 'NULL':
            update_q = self.connectionHelper.queries.update_tab_attrib_with_value(
                self.get_fully_qualified_table_name(tabname), attrib, val)
        else:
            datatype = self.get_datatype((tabname, attrib))
            if datatype in NON_TEXT_TYPES:
                update_q = self.connectionHelper.queries.update_tab_attrib_with_value(
                    self.get_fully_qualified_table_name(tabname), attrib, get_format(datatype, val))
            else:
                update_q = self.connectionHelper.queries.update_tab_attrib_with_quoted_value(
                    self.get_fully_qualified_table_name(tabname), attrib, val)
        self.connectionHelper.execute_sql([update_q])

    def get_cnf_pinned_or_none(self, tabname: str, attrib: str):
        pin = getattr(self, 'cnf_pin_values', None) or {}
        return pin.get((tabname, attrib), None)

    def get_s_val(self, attrib: str, tabname: str) -> Union[int, float, date, str]:
        # B13: prefer CNF-pinned route value when available.
        getter = getattr(self, 'get_cnf_pinned_or_none', None)
        pinned = getter(tabname, attrib) if callable(getter) else GenerationPipeLineBase.get_cnf_pinned_or_none(self, tabname, attrib)
        if pinned is not None:
            return pinned
        datatype = self.get_datatype((tabname, attrib))
        if datatype in NON_TEXT_TYPES:
            if (tabname, attrib) in self.filter_attrib_dict.keys():
                lb = self.filter_attrib_dict[(tabname, attrib)][0]
                val = get_boundary_value(lb, is_ub=False)
            else:
                val = get_dummy_val_for(datatype)
            # val = ast.literal_eval(get_format(datatype, val))
        else:
            if (tabname, attrib) in self.filter_attrib_dict.keys():
                val = self.get_s_val_for_textType(attrib, tabname)
                self.logger.debug(val)
                val = val.replace('%', '')
            else:
                val = get_char(get_dummy_val_for('char'))
        return val

    def get_other_than_dmin_val_nonText(self, attrib: str, tabname: str, prev) -> Union[int, float, date, str]:
        key = (tabname, attrib)
        datatype = self.get_datatype(key)
        if key not in self.filter_attrib_dict:
            return get_dummy_val_for(datatype)

        if len(self.filter_attrib_dict[key]) == 1:
            self.logger.info("Cannot generate a new s-val. Giving the old one!")
            return prev

        lb, ub = self.filter_attrib_dict[key][0], self.filter_attrib_dict[key][-1]
        lb = get_boundary_value(lb, is_ub=False)
        ub = get_boundary_value(ub, is_ub=True)
        # A filter bound may be a generic domain extreme when the real bound is
        # encoded as an AOA predicate. Intersect with AOA-implied bounds so the
        # probe does not eliminate every result row.
        try:
            aoa_lb, aoa_ub = self.get_aoa_implied_bounds(tabname, attrib, datatype)
            lb = max(lb, aoa_lb)
            ub = min(ub, aoa_ub)
        except Exception:
            pass
        val = ub if prev == lb else lb
        if val == prev:
            val = ub if lb != ub else prev
        return val

    def get_aoa_implied_bounds(self, tabname: str, attrib: str, datatype: str):
        """Return (lb, ub) implied by AOA predicates for (tabname, attrib), using current dmin values."""
        from ...util.utils import get_min_and_max_val
        i_min, i_max = get_min_and_max_val(datatype)
        lb, ub = i_min, i_max
        gen_ctx = getattr(self, "_gen_ctx", None)
        if gen_ctx is None:
            return lb, ub
        key = (tabname, attrib)
        le_preds = getattr(gen_ctx, "global_aoa_le_predicates", []) or []
        l_preds = getattr(gen_ctx, "global_aoa_l_predicates", []) or []
        def _current_val(attrib):
            if not isinstance(attrib, tuple):
                return attrib
            tab, col = attrib[0], attrib[1]
            try:
                fqtn = self.get_fully_qualified_table_name(tab)
                val = self.connectionHelper.execute_sql_fetchone_0(
                    self.connectionHelper.queries.select_attribs_from_relation([col], fqtn))
                if val is not None:
                    return val
            except Exception:
                pass
            return self.get_dmin_val(col, tab)

        for pred in le_preds:
            l_attrib, r_attrib = pred[0], pred[1]
            if r_attrib == key:
                l_val = _current_val(l_attrib)
                if l_val is not None and l_val > lb:
                    lb = l_val
            if l_attrib == key:
                r_val = _current_val(r_attrib)
                if r_val is not None and r_val < ub:
                    ub = r_val
        for pred in l_preds:
            l_attrib, r_attrib = pred[0], pred[1]
            if r_attrib == key:
                l_val = _current_val(l_attrib)
                if l_val is not None and l_val >= lb:
                    lb = l_val
            if l_attrib == key:
                r_val = _current_val(r_attrib)
                if r_val is not None and r_val <= ub:
                    ub = r_val
        return lb, ub

    def get_different_s_val(self, attrib: str, tabname: str, prev) -> Union[int, float, date, str]:
        datatype = self.get_datatype((tabname, attrib))
        self.logger.debug(f"datatype of {attrib} is {datatype}")
        if datatype in NON_TEXT_TYPES:
            if (tabname, attrib) in self.filter_attrib_dict.keys():
                val = self.get_other_than_dmin_val_nonText(attrib, tabname, prev)
            else:
                lb, ub = self.get_aoa_implied_bounds(tabname, attrib, datatype)
                from ...util.utils import get_min_and_max_val
                i_min, i_max = get_min_and_max_val(datatype)
                if lb > i_min or ub < i_max:
                    # AOA-constrained: pick a value satisfying AOA bounds, different from prev.
                    def _dist(a, b):
                        if datatype == 'date':
                            return abs((a - b).days)
                        return abs(float(a) - float(b))
                    if prev <= lb:
                        val = ub
                    elif prev >= ub:
                        val = lb
                    else:
                        val = ub if _dist(ub, prev) >= _dist(prev, lb) else lb
                    if val == prev:
                        val = get_unused_dummy_val(datatype, [prev])
                else:
                    val = get_unused_dummy_val(datatype, [prev])
            if datatype == 'date':
                val = ast.literal_eval(get_format(datatype, val))
        else:
            if (tabname, attrib) in self.filter_attrib_dict.keys():
                val = self.get_s_val_for_textType(attrib, tabname)
                self.logger.debug(val)
                val = val.replace('%', '')
            else:
                val = get_char(get_unused_dummy_val('char', [prev]))
        return val

    def find_tabname_for_given_attrib(self, find_attrib) -> str:
        for tab_key in self.global_all_attribs.keys():
            if find_attrib in self.global_all_attribs[tab_key]:
                return tab_key

    # ---- CNF/route-aware probe helpers (guarded; legacy no-op when CNF absent) ----
    def has_structured_cnf(self) -> bool:
        try:
            from ..disjunction.routes import has_cnf_routes
            return has_cnf_routes(getattr(self, 'cnf', None))
        except Exception:
            return False

    def set_cnf_probe_route(self, route, sync_context: bool = True):
        if not self.has_structured_cnf() or route is None:
            self.cnf_route = None
            self.cnf_pin_values = {}
        else:
            try:
                from ..disjunction.routes import route_pin_values
                self.cnf_route = route
                self.cnf_pin_values = route_pin_values(route) or {}
            except Exception:
                self.cnf_route = route
                self.cnf_pin_values = {}
        if sync_context and getattr(self, '_gen_ctx', None) is not None:
            try:
                self._gen_ctx.cnf_route = self.cnf_route
                self._gen_ctx.cnf_pin_values = copy.deepcopy(self.cnf_pin_values)
            except Exception:
                pass
        return self.cnf_pin_values

    def get_cnf_freeing_route_for_attr(self, attr):
        if not self.has_structured_cnf():
            return None
        try:
            from ..disjunction.filter_structure import select_freeing_route_for_attr
            return select_freeing_route_for_attr(self.cnf, attr)
        except Exception:
            return None

    def get_cnf_attr_domain(self, attr, route=None):
        if not self.has_structured_cnf():
            return None
        try:
            from ..disjunction.filter_structure import Domain, attr_domain_under_route
            route = self.cnf_route if route is None else route
            return attr_domain_under_route(self.cnf, route, attr, global_domain=Domain(kind='free'))
        except Exception:
            return None

    def get_cnf_distinct_values(self, attr, count=2, route=None, fallback=None):
        if not self.has_structured_cnf():
            return list((fallback or [])[:count])
        try:
            from ..disjunction.filter_structure import sample_values_from_domain
            domain = self.get_cnf_attr_domain(attr, route=route)
            vals = sample_values_from_domain(domain, count=count, fallback=fallback)
            return vals if vals else list((fallback or [])[:count])
        except Exception:
            return list((fallback or [])[:count])

    def save_db_values_for_attrs(self, attrs):
        saved = {}
        for tab, col in attrs or []:
            try:
                prev = self.connectionHelper.execute_sql_fetchone_0(
                    self.connectionHelper.queries.select_attribs_from_relation([col], tab))
                saved[(tab, col)] = prev
            except Exception:
                pass
        return saved

    def restore_db_values_for_attrs(self, saved):
        for (tab, col), val in (saved or {}).items():
            try:
                self.update_with_val(col, tab, val)
            except Exception:
                try:
                    self.update_attrib_in_table(col, val, tab)
                except Exception:
                    pass

    def apply_cnf_route_to_db(self, route=None, attrs=None):
        """Apply CNF route pin values to DB and return restore state.
        Returns (saved_values, prev_route, prev_pin_values). No-op when CNF absent."""
        prev_route = self.cnf_route
        prev_pins = copy.deepcopy(getattr(self, 'cnf_pin_values', {}) or {})
        if not self.has_structured_cnf():
            return {}, prev_route, prev_pins
        if route is None:
            route = self.cnf_route
        if route is None:
            return {}, prev_route, prev_pins
        try:
            from ..disjunction.routes import route_pin_values
            pin_values = route_pin_values(route) or {}
        except Exception:
            pin_values = {}
        target_attrs = list(attrs) if attrs is not None else list(pin_values.keys())
        saved = self.save_db_values_for_attrs(target_attrs)
        self.set_cnf_probe_route(route, sync_context=True)
        for (tab, col), val in pin_values.items():
            if attrs is not None and (tab, col) not in attrs:
                continue
            if val is None:
                continue
            try:
                self.update_with_val(col, tab, val)
            except Exception:
                pass
        return saved, prev_route, prev_pins

    def restore_cnf_probe_state(self, saved_values, prev_route, prev_pin_values, sync_context: bool = True):
        self.restore_db_values_for_attrs(saved_values)
        self.cnf_route = prev_route
        self.cnf_pin_values = copy.deepcopy(prev_pin_values or {})
        if sync_context and getattr(self, '_gen_ctx', None) is not None:
            try:
                self._gen_ctx.cnf_route = self.cnf_route
                self._gen_ctx.cnf_pin_values = copy.deepcopy(self.cnf_pin_values)
            except Exception:
                pass
