import ast
import copy
import logging
import math

from .dataclass.genPipeline_context import GenPipelineContext
from .projection import get_param_values_external
from ..util.utils import is_number, get_dummy_val_for, get_val_plus_delta, get_format, get_char, get_format_for_agg
from ...src.core.abstract.GenerationPipeLineBase import GenerationPipeLineBase, get_boundary_value
from ..util.constants import NUMBER_TYPES, NON_TEXT_TYPES
from ...src.util.constants import SUM, AVG, MIN, MAX, COUNT, COUNT_STAR
from ...src.util.constants import min_int_val, max_int_val


def get_k_value_for_number(a, b):
    if a == b:
        k_value = 1
        if a == 2:
            k_value = 2
        agg_array = [SUM, k_value * a + b, AVG, a, MIN, a, MAX, a, COUNT, k_value + 1]
    else:
        constraint_array = [0, a, b, a - 1, b - 1]
        if a != 0:
            constraint_array.append((a - b) / a)
        if a != 1:
            constraint_array.append((1 - b) / (a - 1))
        discriminant = (a - 2) ** 2 - (4 * (1 - b))
        if discriminant >= 0:
            constraint_array.append(((a - 2) + math.sqrt(discriminant)) / 2)
        k_value = 2
        while k_value in constraint_array:
            k_value = k_value + 1
        avg = round((k_value * a + b) / (k_value + 1), 2)
        agg_array = [SUM, k_value * a + b, AVG, avg, MIN, min(a, b), MAX, max(a, b), COUNT, k_value + 1]
    return k_value, agg_array


def get_k_value(attrib, filter_attrib_dict, groupby_key_flag, tabname, datatype, c):
    key = (tabname, attrib)
    if groupby_key_flag and datatype in NUMBER_TYPES:
        a = b = 3
        k_value = 1
        agg_array = [SUM, k_value * a + b, AVG, a, MIN, a, MAX, a, COUNT, k_value + 1]
    elif key in filter_attrib_dict:
        filtered = filter_attrib_dict[key]
        if datatype in NUMBER_TYPES:
            # PRECISION TO BE TAKEN CARE FOR NUMERIC
            lb, ub = filtered[0], filtered[1]
            lb = get_boundary_value(lb, is_ub=False)
            ub = get_boundary_value(ub, is_ub=True)
            dummy_int_val = get_dummy_val_for('int')
            # Both probe values must satisfy the extracted filter. The old
            # construction could place b below lb, which removes the group in
            # the oracle query and makes the predicted aggregate wrong.
            a = min(max(dummy_int_val + c, lb), ub)
            if ub > lb:
                b = min(a + 1, ub)
                if b == a and a > lb:
                    b = a - 1
            else:
                b = a
            if a == b and ub > lb:
                a, b = lb, min(lb + 1, ub)
            k_value, agg_array = get_k_value_for_number(a, b)
        elif datatype == 'date':
            date_lb, date_ub = filtered[0], filtered[1]
            date_lb = get_boundary_value(date_lb, is_ub=False)
            date_ub = get_boundary_value(date_ub, is_ub=True)
            a = get_format_for_agg('date', date_lb)
            date_val_plus_1 = get_val_plus_delta('date', date_lb, 1)
            b = get_format_for_agg('date', min(date_val_plus_1, date_ub))
            k_value = 1
            agg_array = [MIN, min(a, b), MAX, max(a, b)]
            #a = ast.literal_eval(a)
            #b = ast.literal_eval(b)
        else:
            # string filter attribute
            if '_' in filtered:
                a = filtered.replace('_', 'a')
                b = filtered.replace('_', 'b')
            else:
                a = filtered.replace('%', 'a', 1)
                b = filtered.replace('%', 'b', 1)
            a = a.replace('%', '')
            b = b.replace('%', '')
            k_value = 1
            agg_array = [MIN, min(a, b), MAX, max(a, b)]
    else:
        if datatype == 'date':
            a = get_format('date', get_dummy_val_for('date'))
            b = get_format('date', get_val_plus_delta('date', get_dummy_val_for('date'), 1))
            k_value = 1
            agg_array = [MIN, min(a, b), MAX, max(a, b)]
        elif datatype in NUMBER_TYPES:
            # Combination which gives all different results for aggregation
            a = 5
            b = 8
            k_value = 2
            agg_array = [SUM, 18, AVG, 6, MIN, 5, MAX, 8, COUNT, 3]
        else:
            # String data type
            a = get_char(get_dummy_val_for('char'))
            b = get_char(get_val_plus_delta('char', get_dummy_val_for('char'), 1))
            k_value = 1
            agg_array = [MIN, min(a, b), MAX, max(a, b)]
    # print(tabname, attrib, a, b)
    return a, agg_array, b, k_value


def get_no_of_rows(attrib_list_inner, k_value, key_list, tabname, tabname_inner, result_index, deps):
    same_tab_flag = False
    if tabname_inner == tabname:
        no_of_rows = k_value + 1
        same_tab_flag = True
    else:
        no_of_rows = 1
    key_path_flag = any(val in key_list for val in attrib_list_inner)
    if not same_tab_flag and key_path_flag:
        no_of_rows = 2
    return no_of_rows


class Aggregation(GenerationPipeLineBase):
    def __init__(self, connectionHelper,
                 genPipelineCtx: GenPipelineContext,
                 pgao_Ctx):
        super().__init__(connectionHelper, "Aggregation", genPipelineCtx)
        self.global_aggregated_attributes = None
        self.global_projected_attributes = pgao_Ctx.projected_attribs
        self.has_groupby = pgao_Ctx.has_groupby
        self.global_groupby_attributes = pgao_Ctx.group_by_attrib
        self.dependencies = pgao_Ctx.projection_dependencies
        self.solution = pgao_Ctx.projection_solution
        self.param_list = pgao_Ctx.projection_param_list

    def doExtractJob(self, query):
        # AsSUMing NO DISTINCT IN AGGREGATION

        self.global_aggregated_attributes = [(element, '') for element in self.global_projected_attributes]
        if not self.has_groupby:
            return False

        debug_enabled = self.logger.isEnabledFor(logging.DEBUG)
        groupby_set = set(self.global_groupby_attributes)
        joined_attrib_set = set(self.joined_attribs) if self.joined_attribs is not None else set()

        join_edge_by_attrib = {}
        for edge in self.global_join_graph:
            for attr in edge:
                join_edge_by_attrib.setdefault(attr, edge)

        dep_result_indices = {}
        for j, dep in enumerate(self.dependencies):
            candidate_attribs = set()
            for d in dep:
                candidate_attribs.update(d)
            for attr in candidate_attribs:
                dep_result_indices.setdefault(attr, []).append(j)

        core_relation_index = {}
        for idx, tab in enumerate(self.core_relations):
            core_relation_index.setdefault(tab, idx)
        attrib_index_by_tab = {}
        for tab, attrs in self.global_all_attribs.items():
            index_map = {}
            for idx, attr in enumerate(attrs):
                index_map.setdefault(attr, idx)
            attrib_index_by_tab[tab] = index_map

        for tabname in self.core_relations:
            attrib_list = self.global_all_attribs[tabname]
            for c, attrib in enumerate(attrib_list):
                # check if it is a key attribute
                key_list = join_edge_by_attrib.get(attrib, [])

                if debug_enabled:
                    self.logger.debug("Group By Attribs", self.global_groupby_attributes)
                    self.logger.debug("Key attribs", key_list)
                if any(_key in groupby_set for _key in key_list):
                    continue
                if debug_enabled:
                    self.logger.debug("Not groupby", attrib)
                # Attribute Filtering
                if attrib in groupby_set:
                    continue

                result_index_list = [j for j in dep_result_indices.get(attrib, [])
                                     if self.global_aggregated_attributes[j][1] == '']

                groupby_key_flag = attrib in joined_attrib_set and attrib in groupby_set
                if result_index_list:
                    prev_route = self.cnf_route
                    prev_pins = copy.deepcopy(getattr(self, 'cnf_pin_values', {}) or {})
                    if self.has_structured_cnf():
                        route = self.get_cnf_freeing_route_for_attr((tabname, attrib)) or self.cnf_route
                        self.set_cnf_probe_route(route)
                    try:
                        datatype = self.get_datatype((tabname, attrib))
                        a, base_agg_array, b, k_value = self._get_k_value_cnf_aware(
                            attrib, groupby_key_flag, tabname, datatype, c)
                        for result_index in result_index_list:
                            agg_array = base_agg_array
                            self.truncate_core_relations()
                            temp_vals = []
                            max_no_of_rows = self.insert_for_inner(a, attrib, b, k_value, key_list, tabname, temp_vals,
                                                                   result_index)
                            if debug_enabled:
                                self.logger.debug(self.dependencies, result_index,
                                                  key_list, tabname, temp_vals, result_index)

                            if len(self.solution[result_index]) >= 1:
                                if debug_enabled:
                                    self.logger.debug("Temp values", temp_vals)  # FOR DEBUG
                                s = 0
                                mi = max_int_val
                                ma = min_int_val
                                temp_ar = []
                                local_sol = self.solution[result_index]
                                for ele in self.dependencies[result_index]:
                                    local_tabname = ele[0]
                                    local_attrib = ele[1]
                                    local_attrib_index = attrib_index_by_tab[local_tabname][local_attrib]
                                    vals_sp = temp_vals[core_relation_index[local_tabname]]
                                    l = [row[local_attrib_index] for row in vals_sp]
                                    temp_ar.append((local_attrib, l))
                                temp_ar = sorted(temp_ar, key=lambda x: x[0])
                                if debug_enabled:
                                    self.logger.debug("Temp Arr", temp_ar)  # FOR DEBUG
                                for t in range(len(temp_ar)):
                                    if len(temp_ar[t][1]) < max_no_of_rows:
                                        temp_ar[t][1].extend(
                                            [temp_ar[t][1][0]] * (max_no_of_rows - len(temp_ar[t][1])))
                                is_numeric = True
                                try:
                                    probe_values = [[float(temp_ar[j][1][_row])
                                                     for j in range(len(self.dependencies[result_index]))]
                                                    for _row in range(max_no_of_rows)]
                                except (TypeError, ValueError):
                                    is_numeric = False
                                    probe_values = [[str(temp_ar[j][1][_row])
                                                     for j in range(len(self.dependencies[result_index]))]
                                                    for _row in range(max_no_of_rows)]
                                eqn_values = []
                                for inter_val in probe_values:
                                    if is_numeric:
                                        temp_arr = get_param_values_external(inter_val)
                                        if debug_enabled:
                                            self.logger.debug("Coeffs", temp_arr, local_sol)  # FOR DEBUG
                                        inter_val = list(temp_arr) + [1]
                                        eqn = sum(val * local_sol[j][0]
                                                  for j, val in enumerate(inter_val[:len(local_sol)]))
                                    else:
                                        eqn = inter_val[0]
                                    eqn_values.append(eqn)
                                    s += eqn if is_numeric else 0
                                    if is_numeric:
                                        mi = min(mi, eqn)
                                        ma = max(ma, eqn)
                                if not is_numeric:
                                    mi, ma = min(eqn_values), max(eqn_values)
                                if debug_enabled:
                                    self.logger.debug("no_of_rows ", max_no_of_rows)
                                av = (s / max_no_of_rows) if max_no_of_rows else 0
                                if debug_enabled:
                                    self.logger.debug("Temp Array", temp_ar)
                                    self.logger.debug("SUM, AVG, MIN, MAX", s, av, mi, ma)
                                if is_numeric:
                                    agg_array = [SUM, s, AVG, av, MIN, mi, MAX, ma, COUNT, max_no_of_rows]
                                else:
                                    agg_array = [MIN, mi, MAX, ma]
                            new_result = self.app.doJob(query)
                            if debug_enabled:
                                self.logger.debug("New Result", new_result)  # FOR DEBUG
                                self.logger.debug("Comaparison", agg_array)  # FOR DEBUG
                            if self.app.isQ_result_empty(new_result):
                                self.logger.error('some error in generating new database. '
                                                  'Result is empty. Can not identify aggregation')
                                return False
                            nullfree_rows = self.app.get_all_nullfree_rows(new_result)
                            if len(nullfree_rows) > 1:
                                continue

                            self.analyze(agg_array, self.global_projected_attributes[result_index], nullfree_rows, result_index)
                    finally:
                        if self.has_structured_cnf():
                            self.cnf_route = prev_route
                            self.cnf_pin_values = copy.deepcopy(prev_pins)
                            self.set_cnf_probe_route(prev_route)

        for i in range(len(self.global_projected_attributes)):
            if self.global_projected_attributes[i] == '':
                self.global_aggregated_attributes[i] = ('', COUNT_STAR)

        return True

    def insert_for_inner(self, a, attrib, b, k_value, key_list, tabname, temp_vals, result_index):
        max_no_of_rows = 0
        debug_enabled = self.logger.isEnabledFor(logging.DEBUG)
        key_set = set(key_list)
        # For this table (tabname) and this attribute (attrib), fill all tables now
        for tabname_inner in self.core_relations:
            attrib_list_inner = self.global_all_attribs[tabname_inner]
            insert_rows = []
            no_of_rows = get_no_of_rows(attrib_list_inner, k_value, key_set, tabname, tabname_inner, result_index,
                                        self.dependencies)

            if no_of_rows > max_no_of_rows:
                max_no_of_rows = no_of_rows

            if debug_enabled:
                self.logger.debug("tabname ", tabname, " tabname_inner ", tabname_inner, " no_of_rows ", no_of_rows)
            attrib_list_str = ",".join(attrib_list_inner)
            att_order = f"({attrib_list_str})"

            column_specs = []
            for attrib_inner in attrib_list_inner:
                datatype = self.get_datatype((tabname_inner, attrib_inner))
                if attrib_inner == attrib or attrib_inner in key_set:
                    column_specs.append((attrib_inner, datatype, True, None))
                    continue
                # B13 (guarded): prefer CNF route-pinned value for non-varying fillers.
                pinned = self.get_cnf_pinned_or_none(tabname_inner, attrib_inner) if hasattr(self, 'get_cnf_pinned_or_none') else None
                if pinned is not None:
                    column_specs.append((attrib_inner, datatype, False, pinned))
                    continue
                filter_key = (tabname_inner, attrib_inner)
                if datatype in NON_TEXT_TYPES:
                    # One shared bound-aware generator is used by every probe
                    # stage. This keeps absorbed AOA constants from being lost
                    # when a concrete bound is no longer in filter_attrib_dict.
                    if self.has_probe_bounds(tabname_inner, attrib_inner, datatype):
                        val = self.get_s_value_within_bounds(tabname_inner, attrib_inner,
                                                             datatype=datatype, prefer='lb')
                    elif datatype == 'date':
                        val = get_val_plus_delta('date', get_dummy_val_for('date'), 2)
                    else:
                        val = get_dummy_val_for('int')
                    filler = (ast.literal_eval(get_format('date', val))
                              if datatype == 'date' else val)
                else:
                    # check for filter
                    if filter_key in self.filter_attrib_dict:
                        attrib_val = self.get_s_val_for_textType(attrib_inner, tabname_inner)
                        plus_val = attrib_val.replace('%', '')
                    else:
                        plus_val = get_char(get_val_plus_delta('char', get_dummy_val_for('char'), 2))
                    filler = plus_val
                column_specs.append((attrib_inner, datatype, False, filler))

            for k in range(no_of_rows):
                last_row = k == no_of_rows - 1
                insert_values = []
                for attrib_inner, datatype, is_special, filler in column_specs:
                    val = (b if last_row else a) if is_special else filler
                    insert_values.append(val)
                    if debug_enabled:
                        self.logger.debug(tabname_inner, attrib_inner, datatype, val)
                insert_rows.append(tuple(insert_values))

            if debug_enabled:
                self.logger.debug("Attribute Ordering: ", att_order)  # FOR DEBUG
                self.logger.debug("Rows: ", insert_rows)  # FOR DEBUG
            temp_vals.append(insert_rows)
            self.insert_attrib_vals_into_table(att_order, attrib_list_inner, insert_rows, tabname_inner)
        return max_no_of_rows

    def analyze(self, agg_array, attrib, new_result, result_index):
        debug_enabled = self.logger.isEnabledFor(logging.DEBUG)
        if debug_enabled:
            self.logger.debug("analyze")
        new_result = [x.strip() for x in new_result[0]]
        check_value = round(float(new_result[result_index]), 2) if is_number(new_result[result_index]) \
            else str(new_result[result_index])
        agg_array = [round(x, 2) if isinstance(x, float) else x for x in agg_array]
        for j in range(0, len(agg_array) - 1, 2):
            if debug_enabled:
                self.logger.debug(str(attrib), " ", agg_array[j])
                self.logger.debug(check_value, " ", agg_array[j + 1])
            candidate = agg_array[j + 1]
            if isinstance(check_value, float) and isinstance(candidate, (int, float)):
                # Probe values carry small epsilon offsets, so the predicted
                # aggregate can differ from the observed one in the last bit.
                matched = abs(check_value - float(candidate)) <= max(0.02, abs(float(candidate)) * 0.001)
            else:
                matched = check_value == candidate
            if matched:
                self.global_aggregated_attributes[result_index] = (str(attrib), agg_array[j])
                break

    def _get_k_value_aoa_aware(self, attrib, groupby_key_flag, tabname, datatype, c):
        """Feed the shared effective bounds into the aggregate probe values."""
        key = (tabname, attrib)
        filter_dict = dict(self.filter_attrib_dict)
        if datatype in NON_TEXT_TYPES and self.has_probe_bounds(tabname, attrib, datatype):
            filter_dict[key] = self.get_effective_bounds(tabname, attrib, datatype)
        return get_k_value(attrib, filter_dict, groupby_key_flag, tabname, datatype, c)

    def _get_k_value_cnf_aware(self, attrib, groupby_key_flag, tabname, datatype, c):
        key = (tabname, attrib)
        if self.has_structured_cnf():
            try:
                domain = self.get_cnf_attr_domain(key, route=self.cnf_route)
            except Exception:
                domain = None
            if domain is not None:
                kind = getattr(domain, 'kind', None)
                if kind == 'pinned':
                    vals = getattr(domain, 'values', []) or []
                    v = vals[0] if vals else None
                    if v is not None:
                        if datatype in NUMBER_TYPES:
                            k_value = 1
                            agg_array = [SUM, k_value * v + v, AVG, v, MIN, v, MAX, v, COUNT, k_value + 1]
                            return v, agg_array, v, k_value
                        k_value = 1
                        return v, [MIN, v, MAX, v], v, k_value
                elif kind == 'union':
                    vals = self.get_cnf_distinct_values(key, count=2, route=self.cnf_route)
                    if len(vals) >= 2:
                        a, b = vals[0], vals[1]
                        if datatype in NUMBER_TYPES:
                            try:
                                an, bn = float(a), float(b)
                                if an == 0 and bn != 0:
                                    a, b = b, a
                                k_value, agg_array = get_k_value_for_number(a, b)
                            except Exception:
                                k_value = 1
                                agg_array = [MIN, min(a, b), MAX, max(a, b)]
                        elif datatype == 'date':
                            k_value = 1
                            agg_array = [MIN, min(a, b), MAX, max(a, b)]
                        else:
                            k_value = 1
                            agg_array = [MIN, min(a, b), MAX, max(a, b)]
                        return a, agg_array, b, k_value
                # free/other: fall through to legacy
        return self._get_k_value_aoa_aware(attrib, groupby_key_flag, tabname, datatype, c)
