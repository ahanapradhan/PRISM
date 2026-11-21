import math
import random

import numpy as np
from sympy import symbols, expand, collect, nsimplify, Rational, Integer, simplify
from sympy import nsimplify, collect, simplify, sympify, flatten
from sympy.tensor.array import NDimArray
from sympy.matrices.matrices import MatrixBase

from .dataclass.genPipeline_context import GenPipelineContext
from ..util.constants import CONST_1_VALUE, NUMBER_TYPES, un_precision
from ...src.core.abstract.GenerationPipeLineBase import GenerationPipeLineBase, get_boundary_value
from ...src.core.abstract.abstractConnection import AbstractConnectionHelper
from ...src.util import constants
from ...src.util.utils import count_empty_lists_in, find_diff_idx, get_format


def round_expr(expr, num_digits):
    return expr.xreplace({n: round(n, num_digits) for n in expr.atoms(Rational) if not isinstance(n, Integer)})


def if_dependencies_found_incomplete(projection_names, projection_dep):
    if len(projection_names) > 2:
        empty_deps = count_empty_lists_in(projection_dep)
        if len(projection_dep) - empty_deps < 2:
            return True
    return False


def get_index_of_difference(attrib, new_result, new_result1, projection_dep, tabname):
    new_result1 = new_result1[1:]
    diff = find_diff_idx(new_result1, new_result)
    if diff:
        for d in diff:
            if (tabname, attrib) not in projection_dep[d]:
                projection_dep[d].append((tabname, attrib))
    return projection_dep


def beautify_scalar_func(final_res, local_symbol_list, deps):
    # final_res can arrive as an Array/Matrix (even 1 element); collect() needs an Expr
    if isinstance(final_res, (NDimArray, MatrixBase)):
        elems = flatten(final_res.tolist())
        if len(elems) == 1:
            print(elems[0])
            final_res = elems[0]              # unwrap the single element
        else:                                  # genuine multi-element array: do each element
            raise ValueError("expected scalar, got array")
    final_res = sympify(final_res)
    #print(final_res)

    res_expr = nsimplify(collect(final_res, local_symbol_list))
    attribs = [dep[1] for dep in deps]
    counter_dict = {a: res_expr.count(a) for a in attribs}
    filtered_attribs = [a for a, c in counter_dict.items() if c > 1]
    res_expr = simplify(res_expr)
    for a in filtered_attribs:
        res_expr = collect(res_expr, a, distribute_order_term=False)
    return nsimplify(res_expr)


def _is_range_interval_value(val):
    if not isinstance(val, (tuple, list)) or isinstance(val, (str, bytes)) or len(val) != 2:
        return False
    lo, hi = val[0], val[1]
    if lo is None or hi is None:
        return False
    numeric = (int, float)
    try:
        import decimal
        numeric = (int, float, decimal.Decimal)
    except Exception:
        pass
    if isinstance(lo, bool) or isinstance(hi, bool):
        return False
    # treat as range pair when both look like bounds (numeric/date-like)
    if isinstance(lo, numeric) and isinstance(hi, numeric):
        return True
    try:
        # date/datetime bounds
        if hasattr(lo, 'year') and hasattr(hi, 'year'):
            return True
    except Exception:
        pass
    return False


def _scalar_from_range_interval(val):
    lo, hi = val[0], val[1]
    try:
        if lo == hi:
            return lo
        # midpoint for probe value
        mid = lo + (hi - lo) / 2
        # prefer integer midpoint when bounds are integral
        if isinstance(lo, int) and isinstance(hi, int) and not isinstance(lo, bool) and not isinstance(hi, bool):
            try:
                imid = int(mid)
                if lo <= imid <= hi:
                    return imid
            except Exception:
                pass
        return mid
    except Exception:
        return lo

class Projection(GenerationPipeLineBase):
    def __init__(self, connectionHelper: AbstractConnectionHelper, genPipelineCtx: GenPipelineContext):
        super().__init__(connectionHelper, "Projection", genPipelineCtx)
        self.projection_names = None
        self.projected_attribs = None
        self.dependencies = None
        self.solution = None
        self.syms = []
        """
        List of list of all the subsets of the dependencies of an output column (having more than one dependencies)
        Suppose a column is dependent on a and b, corresponding index of that column in param_list will contain, [a,b,a*b]
        """
        self.param_list = []
        self.rmin_card = 0
        self.or_predicates_dict = {}

    def do_init(self) -> None:
        super().do_init()
        for in_pred in self.filter_in_predicates:
            if not in_pred or len(in_pred) < 4:
                continue
            if str(in_pred[2]).upper() in ('OR_CLAUSE', 'OR') and in_pred[0] == '__OR_CLAUSE__':
                continue
            try:
                self.or_predicates_dict[(in_pred[0], in_pred[1])] = in_pred[3]
            except Exception:
                continue

    def doExtractJob(self, query):
        s_values = []
        projected_attrib, projection_names, projection_dep, check = self.find_projection_dependencies(query, s_values)

        if not check:
            self.logger.error("Some problem while identifying the dependency list!")
            return False
        if if_dependencies_found_incomplete(projection_names, projection_dep):
            for s_v in s_values:
                if s_v[2] is not None:
                    self.update_with_val(s_v[1], s_v[0], s_v[2])
        projected_attrib, projection_names, projection_dep, check = self.find_projection_dependencies(query, s_values)
        if not check:
            self.logger.error("Some problem while identifying the dependency list!")
            return False

        self.logger.debug("Projection Deps: ", projection_dep)
        projection_sol = self.find_solution_on_multi(projected_attrib, projection_dep, query)
        self.projected_attribs = projected_attrib
        self.projection_names = projection_names
        self.dependencies = projection_dep
        self.solution = projection_sol
        self.logger.debug("Result ", projection_names, projected_attrib, projection_sol, self.param_list)
        return True

    def find_projection_dependencies(self, query, s_values):
        new_result = self.app.doJob(query)
        if self.app.isQ_result_empty(new_result):
            self.logger.error("Unmasque: \n some error in generating new database. "
                              "Result is empty. Can not identify "
                              "projections completely.")
            return [], [], [], False

        self.rmin_card = len(new_result)

        projection_names = list(new_result[0])
        projection_coulumn_type = self.get_projection_column_type(query, projection_names)

        new_result = new_result[1:]
        projected_attrib = []
        keys_to_skip = []
        projection_dep = [[] for _ in projection_names]
        s_value_dict = {}

        for entry in self.global_attrib_types:
            tabname = entry[0]
            attrib = entry[1]
            self.logger.debug("Joined attribs: ", self.joined_attribs)
            self.logger.debug("checking for ", tabname, attrib)
            if attrib in self.joined_attribs:
                val, keys_to_skip = self.check_impact_of_bulk_attribs(attrib, new_result, projection_dep, query,
                                                                      tabname, keys_to_skip, s_value_dict)
            else:
                val = self.check_impact_of_single_attrib(attrib, new_result, projection_dep, query, tabname)
            s_values.append((tabname, attrib, val))

        in_pred_attribs = {
            p[1] for p in self.filter_in_predicates
            if p and len(p) > 1 and not (str(p[2]).upper() in ('OR_CLAUSE', 'OR') and p[0] == '__OR_CLAUSE__')
        }
        for i in range(len(projection_names)):
            if len(projection_dep[i]) == 1:
                attrib_tup = projection_dep[i][0]
                projected_attrib.append(attrib_tup[1])
            else:
                if (len(projection_dep[i]) == 0
                        and projection_names[i] in in_pred_attribs
                        and new_result[0][i] != CONST_1_VALUE):
                    # IN/OR-constrained projected columns may look constant in D_min;
                    # keep the attribute reference instead of a literal constant.
                    projected_attrib.append(projection_names[i])
                elif len(projection_dep[i]) == 0 and new_result[0][i] != CONST_1_VALUE:
                    # If no dependency is there and value is not 1 in result this means it is constant.
                    # With CNF/OR union domains (possibly cross-column), keep attr ref if non-singleton.
                    if self.has_structured_cnf() and self._is_cnf_non_singleton_projection(projection_names[i]):
                        projected_attrib.append(projection_names[i])
                    else:
                        projected_attrib.append(get_format(projection_coulumn_type[i], new_result[0][i]))
                else:
                    # No dependency and value is one so in groupby file will differentiate between count or 1.
                    projected_attrib.append('')

        return projected_attrib, projection_names, projection_dep, True

    def get_projection_column_type(self, query, projection_names):
        mod_query = query.replace(";", '')
        datatype_names = []
        for i in projection_names:
            typecheck_query = str(
                'SELECT pg_typeof(' + i + ') AS data_type FROM (' + mod_query + ') AS subquery limit 1;')
            type_result = self.app.doJob(typecheck_query)
            modified_str = str(type_result[1])
            modified_str = modified_str[1:-2]
            datatype_names.append(modified_str)
        datatype_names = [element.strip("'") for element in datatype_names]
        return datatype_names

    def check_impact_of_bulk_attribs(self, attrib, new_result, projection_dep, query, tabname,
                                     keys_to_skip, s_value_dict):
        if attrib in keys_to_skip:
            return s_value_dict[attrib], keys_to_skip
        join_tabnames = []
        other_attribs = self.get_other_attribs_in_eqJoin_grp(attrib)
        val, prev = self.update_attrib_to_see_impact(attrib, tabname)
        self.update_attribs_bulk(join_tabnames, other_attribs, val)
        self.see_d_min()
        new_result1 = self.app.doJob(query)
        self.update_with_val(attrib, tabname, prev)
        self.update_attribs_bulk(join_tabnames, other_attribs, prev)

        if not self.app.isQ_result_empty(new_result1):
            projection_dep = get_index_of_difference(attrib, new_result, new_result1, projection_dep, tabname)
        keys_to_skip = keys_to_skip + other_attribs
        for other_attrib in other_attribs:
            s_value_dict[other_attrib] = val
        return val, keys_to_skip

    def _scalar_probe_value(self, val):
        if _is_range_interval_value(val):
            return _scalar_from_range_interval(val)
        return val

    def check_impact_of_single_attrib(self, attrib, new_result, projection_dep, query, tabname):
        for fe in self.global_filter_predicates:
            if fe[1] == attrib and (fe[2] == 'equal' or fe[2] == '=') and fe[1] not in self.joined_attribs:
                return
        key = (tabname, attrib)
        if self.has_structured_cnf():
            return self._check_impact_cnf(attrib, new_result, projection_dep, query, tabname, key)

        if key in self.or_predicates_dict:
            in_vals = list(self.or_predicates_dict[key])
            prev = self.connectionHelper.execute_sql_fetchone_0(
                self.connectionHelper.queries.select_attribs_from_relation([attrib],
                                                                            self.get_fully_qualified_table_name(tabname)))
            alt = None
            alt_src = None
            for v in in_vals:
                sv = self._scalar_probe_value(v)
                if str(sv) != str(prev):
                    alt = sv
                    alt_src = v
                    break
            if alt is None:
                self.logger.debug("Could not find alternative IN value! Cannot verify impact!")
                return
            self.logger.debug(f"update {tabname}.{attrib} with IN alternative {alt_src if alt_src is not None else alt} that had previous value {prev}")
            self.update_with_val(attrib, tabname, alt)
            new_result1 = self.app.doJob(query)
            self.update_with_val(attrib, tabname, prev)
            if not self.app.isQ_result_empty(new_result1):
                projection_dep = get_index_of_difference(attrib, new_result, new_result1, projection_dep, tabname)
            else:
                self.logger.debug("Got empty result!!!!")
            return alt
        val, prev = self.update_attrib_to_see_impact(attrib, tabname)
        if val == prev:
            self.logger.debug("Could not find other s-value! Cannot verify impact!")
            return
        new_result1 = self.app.doJob(query)
        self.update_with_val(attrib, tabname, prev)
        if not self.app.isQ_result_empty(new_result1):
            projection_dep = get_index_of_difference(attrib, new_result, new_result1, projection_dep, tabname)
        else:
            self.logger.debug("Got empty result!!!!")
        return val

    def _check_impact_cnf(self, attrib, new_result, projection_dep, query, tabname, key):
        route = self.get_cnf_freeing_route_for_attr(key) or self.cnf_route
        saved, prev_route, prev_pins = self.apply_cnf_route_to_db(route)
        try:
            fqtn = self.get_fully_qualified_table_name(tabname)
            prev = self.connectionHelper.execute_sql_fetchone_0(
                self.connectionHelper.queries.select_attribs_from_relation([attrib], fqtn))
            domain = self.get_cnf_attr_domain(key, route=self.cnf_route)
            if domain is not None and getattr(domain, 'kind', None) == 'pinned':
                self.logger.debug(f"CNF-pinned singleton for {tabname}.{attrib}; cannot verify impact.")
                return None
            fallback = []
            try:
                fallback.append(self.get_dmin_val(attrib, tabname))
            except Exception:
                pass
            if prev is not None:
                fallback.insert(0, prev)
            candidates = list(self.get_cnf_distinct_values(key, count=4, route=self.cnf_route, fallback=fallback))
            # legacy IN values can still help when domain sampling is coarse
            if key in self.or_predicates_dict:
                for v in list(self.or_predicates_dict[key]):
                    sv = self._scalar_probe_value(v)
                    if sv not in candidates:
                        candidates.append(sv)
            alt = None
            for v in candidates:
                sv = self._scalar_probe_value(v)
                if prev is None or str(sv) != str(prev):
                    alt = sv
                    break
            if alt is None:
                try:
                    alt = self.get_different_s_val(attrib, tabname, prev)
                except Exception:
                    alt = None
            if alt is not None:
                alt = self._scalar_probe_value(alt)
            if alt is None or (prev is not None and str(alt) == str(prev)):
                self.logger.debug(f"Could not find alternative CNF/route value for {tabname}.{attrib}")
                return None
            self.logger.debug(f"[CNF] update {tabname}.{attrib} with value {alt} (prev {prev})")
            self.update_with_val(attrib, tabname, alt)
            new_result1 = self.app.doJob(query)
            self.update_with_val(attrib, tabname, prev)
            if not self.app.isQ_result_empty(new_result1):
                projection_dep = get_index_of_difference(attrib, new_result, new_result1, projection_dep, tabname)
            else:
                self.logger.debug("Got empty result under CNF route probe")
            return alt
        finally:
            self.restore_cnf_probe_state(saved, prev_route, prev_pins)

    def find_solution_on_multi(self, projected_attrib, projection_dep, query):
        sols = []
        for i in range (1,3): #trying to get the solution twice
            solution = []
            for idx_pro, ele in enumerate(projected_attrib):
                self.logger.debug("ele being checked, bravo1", ele, idx_pro)
                if projection_dep[idx_pro] == [] or (
                        len(projection_dep[idx_pro]) < 2 and projection_dep[idx_pro][0][0] == constants.IDENTICAL_EXPR):
                    self.logger.debug("Simple Projection, Continue")
                    # Identical output column, so append empty list and continue
                    solution.append([])
                    self.param_list.append([])
                    self.syms.append([])
                else:
                    value_used = self.construct_value_used_with_dmin()
                    self.logger.debug("Inside else", value_used)
                    if self.has_structured_cnf():
                        solution.append(self._get_solution_cnf(projected_attrib, projection_dep, idx_pro, value_used, query))
                    else:
                        solution.append(self.get_solution(projected_attrib, projection_dep, idx_pro, value_used, query))
                    self.logger.debug("viola1",solution)
            sols.append(solution)

        self.logger.debug("First coeff: ", sols[0])
        self.logger.debug("Second coeff: ", sols[1])

        # Function to compare two solutions
        def matching_solutions(sol1, sol2):
            i = 0
            for item1, item2 in zip(sol1, sol2):
                if isinstance(item1, np.ndarray) and isinstance(item2, np.ndarray):
                    if not np.allclose(item1, item2):
                        return False, i
                elif isinstance(item1, list) and isinstance(item2, list):
                    if item1 != item2:
                        return False, i
                else:
                    return False, i
                i += 1
            return True, i

        if sols[0] is None:
            return sols[1] if sols[1] is not None else print("Singular matrix error")

        if sols[1] is None:
            return sols[0]

        sols_comparison, index = matching_solutions(sols[0], sols[1])
        if sols_comparison:
            return sols[0]
        else:
            print("Projected attribute in place",index+1, "in extracted query is not extracted correctly.")
            # print("Solution 1 ", sols[0][index])
            # print("Solution 2 ", sols[1][index])
        return sols[0]

    """
    Solve Ax=b to get the expression of the output column
    """

    def get_solution(self, projected_attrib, projection_dep, idx, value_used, query):
        self.logger.debug("filters: ", self.filter_attrib_dict)
        dep = sorted(projection_dep[idx], key=lambda x: x[1])
        n = len(dep)
        sym_string = ''
        for i in dep:
            sym_string += (i[1] + " ")
        res = 1
        if n > 1:
            syms = symbols(sym_string)
            local_symbol_list = syms
            syms = sorted(syms, key=lambda x: str(x))
            self.logger.debug("symbols", syms)
            for i in syms:
                res *= (1 + i)
            self.logger.debug("Sym List", expand(res).args)
            self.syms.append(get_param_values_external(syms))
            self.logger.debug("Another List", self.syms)
        else:
            self.syms.append([symbols(sym_string)])
            local_symbol_list = self.syms[-1]
            self.logger.debug("Another List", self.syms, idx)
        if n == 1 and self.attrib_types_dict[(dep[0][0], dep[0][1])] not in NUMBER_TYPES:
            self.param_list.append([dep[0][1]])
            projected_attrib[idx] = dep[0][1]
            return [[1]]

        coeff = np.zeros((2 ** n, 2 ** n))
        np.set_printoptions(formatter={'float': lambda x: f"{x:.{un_precision + 1}f}"})

        for i in range(n):
            coeff[0][i] = value_used[value_used.index(dep[i][1]) + 1]
        temp_array = get_param_values_external(coeff[0][:n])
        for i in range(2 ** n - 1):
            # Given the values of the n dependencies, we form the rest 2^n - n combinations
            coeff[0][i] = temp_array[i]
        coeff[0][2 ** n - 1] = 1

        local_param_list = self.get_param_list(sorted([i[1] for i in dep]))
        self.logger.debug("Param List", local_param_list)
        self.param_list.append(local_param_list)

        self.__infinite_loop(coeff, dep)
        b = np.zeros((2 ** n, 1))
        try:
            for i in range(2 ** n):
                for j, tab_attrib in enumerate(dep):
                    col = tab_attrib[1]  # self.param_list[idx][j]
                    value = coeff[i][j]
                    joined_cols = self.get_other_attribs_in_eqJoin_grp(col)
                    joined_cols.append(col)
                    for j_c in joined_cols:
                        self.update_attrib_in_table(j_c, value, self.find_tabname_for_given_attrib(j_c))
                        self.logger.debug(f" update {j_c} with {value}")

                exe_result = self.app.doJob(query)
                self.logger.debug(f"Exe result: {exe_result}")
                if not self.app.isQ_result_no_full_nullfree_row(exe_result):
                    null_free_row = self.app.get_nullfree_row(exe_result)
                    b[i][0] = null_free_row[idx]
                    self.logger.debug(f"b[{i}][0] = {b[i][0]}")
                else:
                    self.logger.error("Why null result? Trouble!!! ")
                    raise Exception
            self.logger.debug(dep)
            self.logger.debug("Coeff: ", coeff, "b: ", b)
            # self.logger.debug(f"condition number: {str(np.linalg.cond(coeff))}")
            solution = np.linalg.solve(coeff, b)
            solution = np.around(solution, decimals =un_precision + 1)
            final_res = 0
            for i, ele in enumerate(self.syms[idx]):
                final_res += (ele * solution[i])
            self.logger.debug("Coeff of 1", solution[len(self.syms[idx]) - 1])
            final_res += 1 * solution[-1]
            self.logger.debug("Equation", coeff, b)
            self.logger.debug("Solution", solution)
            res_expr = beautify_scalar_func(final_res, local_symbol_list, dep)
            projected_attrib[idx] = str(round_expr(res_expr, un_precision))
            return solution
        finally:
            # Restore dep attribs (and their join-equivalent cols) to original dmin to avoid
            # AOA/constraint inconsistencies leaking across projection solves.
            for tab_attrib in dep:
                col, tab = tab_attrib[1], tab_attrib[0]
                try:
                    values = self.global_min_instance_dict[tab]
                    attribs, vals = values[0], values[1]
                    dmin_val = vals[attribs.index(col)]
                except Exception:
                    dmin_val = self.get_dmin_val(col, tab)
                joined_cols = self.get_other_attribs_in_eqJoin_grp(col)
                joined_cols.append(col)
                for j_c in joined_cols:
                    j_tab = self.find_tabname_for_given_attrib(j_c)
                    try:
                        j_vals = self.global_min_instance_dict[j_tab]
                        j_attribs, j_vals_list = j_vals[0], j_vals[1]
                        j_dmin = j_vals_list[j_attribs.index(j_c)]
                    except Exception:
                        j_dmin = dmin_val
                    self.update_attrib_in_table(j_c, j_dmin, j_tab)

    def __infinite_loop(self, coeff, dep):
        n = len(dep)
        curr_rank = 1
        outer_idx = 1
        while outer_idx < 2 ** n and curr_rank < 2 ** n:
            prev_idx, prev_rank = outer_idx, curr_rank
            # Same algorithm as above with insertion of random values
            # Additionally checking if rank of the matrix has become 2^n
            for j, ele in enumerate(dep):
                key = (ele[0], ele[1])
                self.__assign_s_val_in_coeffMatrix(coeff, j, key, outer_idx)

            temp_array = get_param_values_external(coeff[outer_idx][:n])
            for j in range(2 ** n - 1):
                coeff[outer_idx][j] = temp_array[j]
            coeff[outer_idx][2 ** n - 1] = 1.0
            m_rank = np.linalg.matrix_rank(coeff)
            if m_rank > curr_rank:
                curr_rank += 1
                outer_idx += 1
            self.logger.debug("outer_idx: ", outer_idx, "curr_rank: ", curr_rank)
            if prev_idx == outer_idx and curr_rank == prev_rank:
                self.logger.debug("It will go to infinite loop!! so breaking...")
                break

    def __assign_next_s_value_for_or_attrib(self, used_vals, tab_attrib):
        in_vals = self.or_predicates_dict[tab_attrib]
        for val in in_vals:
            sv = self._scalar_probe_value(val)
            if not any(str(sv) == str(u) for u in used_vals):
                used_vals.append(sv)
                return sv
        self.logger.error("Insufficient s-value options!")
        return None

    def __assign_s_val_in_coeffMatrix(self, coeff, j, key, outer_idx):
        mini = constants.pr_min
        maxi = constants.pr_max
        s_val = None
        # B13 (guarded): prefer CNF route-pinned value for consistency.
        pin = getattr(self, 'cnf_pin_values', None) or {}
        if key in pin and pin[key] is not None:
            s_val = pin[key]
        elif self.has_structured_cnf():
            s_val = self._pick_cnf_coeff_value(coeff, j, key, outer_idx)
        if s_val is None and key in self.or_predicates_dict.keys():
            s_val = self.__assign_next_s_value_for_or_attrib([self.get_dmin_val(key[1], key[0])], key)
        if s_val is None and key in self.filter_attrib_dict.keys():
            datatype = self.get_datatype(key)
            maxi, mini = self.__get_min_max_s_values(key, maxi, mini)
            if datatype == 'int':
                s_val = random.randrange(mini, maxi)
            elif datatype == 'numeric':
                s_val = round(random.uniform(mini, maxi), un_precision + 1)
        if s_val is None:
            datatype = self.get_datatype(key)
            # Respect AOA predicate bounds (generic: uses AOA predicates + current dmin).
            lb, ub = self.get_aoa_implied_bounds(key[0], key[1], datatype)
            try:
                from ...src.util.utils import get_min_and_max_val
            except Exception:
                from ...util.utils import get_min_and_max_val
            i_min, i_max = get_min_and_max_val(datatype)
            if lb > i_min or ub < i_max:
                mini, maxi = lb, ub
            self.logger.debug(f"mini: {mini}, maxi: {maxi}")
            if datatype == 'numeric':
                lo_f, hi_f = float(mini), float(maxi)
                if lo_f >= hi_f:
                    hi_f = lo_f + 1
                s_val = round(random.uniform(lo_f, hi_f), un_precision + 1)
            elif datatype == 'date':
                if mini == maxi:
                    s_val = mini
                else:
                    try:
                        span = (maxi - mini).days
                        s_val = mini if span <= 0 else mini + __import__('datetime').timedelta(days=random.randint(0, span))
                    except Exception:
                        s_val = mini
            else:
                lo, hi = math.floor(float(mini)), math.ceil(float(maxi))
                if lo >= hi:
                    hi = lo + 1
                s_val = random.randrange(lo, hi)
        s_val = self._scalar_probe_value(s_val)
        self.logger.debug(f"s-value for {key} is {s_val}, assigned to coeff[{outer_idx}][{j}]")
        coeff[outer_idx][j] = s_val

    def __get_min_max_s_values(self, key, maxi, mini):
        lb, ub = get_boundary_value(self.filter_attrib_dict[key][0], is_ub=False), get_boundary_value(
            self.filter_attrib_dict[key][1], is_ub=True)
        if float(mini) > float(lb) and float(maxi) < float(ub):  # good case
            mini, maxi = lb, ub
            return maxi, mini
        mini = max(mini, get_boundary_value(self.filter_attrib_dict[key][0], is_ub=False))
        maxi, ub = min(maxi, get_boundary_value(self.filter_attrib_dict[key][1], is_ub=True)), \
            max(maxi, get_boundary_value(self.filter_attrib_dict[key][1], is_ub=True))
        self.logger.debug(f"mini: {mini}, maxi: {maxi}")
        if mini >= maxi:
            maxi = ub
        return maxi, mini

    def build_equation(self, projected_attrib, projection_dep, projection_sol):
        # print("Full list", self.param_list)
        for idx_pro, ele in enumerate(projected_attrib):
            if projection_dep[idx_pro] == [] or projection_sol[idx_pro] == []:
                continue
            else:
                projected_attrib[idx_pro] = self.build_equation_helper(projection_sol[idx_pro],
                                                                       self.param_list[idx_pro])

    def build_equation_helper(self, solution, dependencies, param_l):
        res_str = ""
        for i in range(len(solution)):
            if solution[i][0] == 0:
                continue
            if res_str == "":
                res_str += (str(solution[i][0]) + "*" + param_l[i]) if solution[i][0] != 1 else param_l[i]
            elif i == len(solution) - 1:
                if solution[i][0] > 0:
                    res_str += "+"
                res_str += str(solution[i][0])
            else:
                if solution[i][0] > 0:
                    res_str += "+"
                res_str += (str(solution[i][0]) + "*" + param_l[i]) if solution[i][0] != 1 else param_l[i]

        self.logger.debug("Result String", res_str)
        return res_str

    def get_param_list(self, deps):
        self.logger.debug(deps)
        subsets = get_subsets(deps)
        subsets = sorted(subsets, key=len)
        self.logger.debug(subsets)
        final_lis = []
        for i in subsets:
            if len(i) < 2 and i == []:
                continue
            temp_str = ""
            for j in range(len(i)):
                temp_str += i[j]
                if j != len(i) - 1:
                    temp_str += "*"
            final_lis.append(temp_str)
        return final_lis

    def construct_value_used_with_dmin(self):
        used_val = [val for data in self.global_min_instance_dict.values() for pair in zip(*data) for val in pair]
        return used_val

    def _resolve_attr_from_projection_name(self, proj_name):
        if not isinstance(proj_name, str):
            return None
        try:
            for (tab, col) in getattr(self, 'global_attrib_types', []) or []:
                if col == proj_name or f"{tab}.{col}" == proj_name:
                    return (tab, col)
        except Exception:
            pass
        try:
            tab = self.find_tabname_for_given_attrib(proj_name)
            if tab is not None:
                return (tab, proj_name)
        except Exception:
            pass
        return None

    def _is_cnf_non_singleton_projection(self, proj_name):
        attr = self._resolve_attr_from_projection_name(proj_name)
        if attr is None or not self.has_structured_cnf():
            return False
        try:
            route = self.get_cnf_freeing_route_for_attr(attr)
            if route is not None:
                dom = self.get_cnf_attr_domain(attr, route=route)
                if dom is None or getattr(dom, 'kind', None) != 'pinned':
                    return True
            dom = self.get_cnf_attr_domain(attr, route=self.cnf_route)
            if dom is not None and getattr(dom, 'kind', None) in ('free', 'union'):
                return True
            from .disjunction.filter_structure import attr_global_union_domain
            g = attr_global_union_domain(self.cnf, attr)
            if g is not None and getattr(g, 'kind', None) != 'pinned':
                return True
        except Exception:
            return False
        return False

    def _select_route_for_deps(self, deps):
        if not self.has_structured_cnf():
            return self.cnf_route
        attrs = [(d[0], d[1]) for d in deps]
        try:
            from .disjunction.routes import iter_routes
            from .disjunction.filter_structure import is_attr_free_under_route
            best = None
            best_score = -1
            for i, route in enumerate(iter_routes(self.cnf)):
                if i >= 64:
                    break
                score = sum(1 for a in attrs if is_attr_free_under_route(self.cnf, route, a))
                if score > best_score:
                    best = route
                    best_score = score
                    if score == len(attrs):
                        break
            return best or self.cnf_route
        except Exception:
            if attrs:
                return self.get_cnf_freeing_route_for_attr(attrs[0]) or self.cnf_route
            return self.cnf_route

    def _get_solution_cnf(self, projected_attrib, projection_dep, idx, value_used, query):
        deps = projection_dep[idx] or []
        route = self._select_route_for_deps(deps)
        saved, prev_route, prev_pins = self.apply_cnf_route_to_db(route)
        try:
            return self.get_solution(projected_attrib, projection_dep, idx, value_used, query)
        finally:
            self.restore_cnf_probe_state(saved, prev_route, prev_pins)

    def _pick_cnf_coeff_value(self, coeff, j, key, outer_idx):
        try:
            domain = self.get_cnf_attr_domain(key, route=self.cnf_route)
        except Exception:
            domain = None
        if domain is None:
            return None
        kind = getattr(domain, 'kind', None)
        if kind == 'free':
            return None
        if kind == 'pinned':
            vals = getattr(domain, 'values', []) or []
            return vals[0] if vals else None
        used = []
        for i in range(outer_idx):
            try:
                used.append(coeff[i][j])
            except Exception:
                pass
        fallback = []
        try:
            fallback.append(self.get_dmin_val(key[1], key[0]))
        except Exception:
            pass
        try:
            candidates = list(self.get_cnf_distinct_values(key, count=max(4, outer_idx + 2), route=self.cnf_route, fallback=fallback))
        except Exception:
            candidates = list(fallback)
        candidates = [self._scalar_probe_value(v) for v in candidates]
        if key in self.or_predicates_dict:
            for v in list(self.or_predicates_dict[key]):
                sv = self._scalar_probe_value(v)
                if not any(str(sv) == str(c) for c in candidates):
                    candidates.append(sv)
        for v in candidates:
            sv = self._scalar_probe_value(v)
            if not any(str(sv) == str(u) for u in used):
                return sv
        return self._scalar_probe_value(candidates[0]) if candidates else None


def get_param_values_external(coeff_arr):
    # print(coeff_arr)
    subsets = get_subsets(coeff_arr)
    subsets = sorted(subsets, key=len)
    # print(subsets)
    final_lis = []
    for i in subsets:
        temp_val = 1
        if len(i) < 2 and i == []:
            continue
        for j in range(len(i)):
            temp_val *= i[j]
        final_lis.append(temp_val)
    return final_lis


def get_subsets(deps):
    res = []
    get_subsets_helper(deps, res, [], 0)
    return res


def get_subsets_helper(deps, res, curr, idx):
    res.append(curr[:])
    for i in range(idx, len(deps)):
        curr.append(deps[i])
        get_subsets_helper(deps, res, curr, i + 1)
        curr.pop()