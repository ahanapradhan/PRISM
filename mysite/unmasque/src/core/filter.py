import copy
import math
import decimal
from typing import List

from ..core.abstract.abstractConnection import AbstractConnectionHelper
from ..core.abstract.un2_where_clause import UN2WhereClause
from ..util.aoa_utils import get_constants_for
from ..util.constants import un_precision
from ..util.error_handling import UnmasqueError
from ..util.error_codes import ERROR_007
from ..util.utils import is_int, get_val_plus_delta, get_min_and_max_val, \
    is_left_less_than_right_by_cutoff, get_format, get_mid_val, get_cast_value


def parse_for_int(val):
    try:
        v_int = int(val)
        v_int = str(val)
    except ValueError:
        v_int = f"\'{str(val)}\'"
    except TypeError:
        v_int = f"\'{str(val)}\'"
    return v_int


def round_ceil(num, places):
    adder = 5 / (10 ** (places + 1))
    ans = decimal.Decimal(num - adder)
    ans = ((ans * (10 ** places)).to_integral_exact(rounding=decimal.ROUND_CEILING)) / (10 ** places)
    return ans


def round_floor(num, places):
    adder = 5 / (10 ** (places + 1))
    # return round(num + adder, places)
    return num


def truncate_value(num, places):
    num = num * (10 ** (places + 1))
    num = math.trunc(num)
    num = num / (10 ** (places + 1))
    return num


class Filter(UN2WhereClause):

    def __init__(self, connectionHelper: AbstractConnectionHelper,
                 core_relations: List[str],
                 global_min_instance_dict: dict):
        super().__init__(connectionHelper, core_relations, global_min_instance_dict, "Filter")
        self.filter_predicates = None

    def do_init(self):
        for tabname in self.core_relations:
            res, desc = self.connectionHelper.execute_sql_fetchall(
                self.connectionHelper.queries.get_column_details_for_table(self.connectionHelper.config.schema,
                                                                           tabname))

            tab_attribs = [row[0].lower() for row in res]
            self.global_all_attribs[tabname] = tab_attribs

            this_attribs = [(tabname, row[0].lower(), row[1].lower()) for row in res]
            self.global_attrib_types.extend(this_attribs)

            for entry in this_attribs:
                self.attrib_types_dict[(entry[0], entry[1])] = entry[2]

            self.global_attrib_max_length.update(
                {(tabname, row[0].lower()): int(str(row[2])) for row in res if is_int(str(row[2]))})

            if self.mock:
                self.insert_into_dmin_dict_values(tabname)

            res, desc = self.connectionHelper.execute_sql_fetchall(
                self.connectionHelper.queries.select_attribs_from_relation(tab_attribs,
                                                                    self.get_fully_qualified_table_name(tabname)))
            for row in res:
                for attrib, value in zip(tab_attribs, row):
                    self.global_d_plus_value[attrib] = value

    def doActualJob(self, args=None):
        query = super().doActualJob(args)
        self.do_init()
        self.filter_predicates = self.get_filter_predicates(query)
        self.logger.debug(self.filter_predicates)
        return self.filter_predicates

    def get_filter_predicates(self, query: str) -> list:
        filter_attribs = []
        for tabname in self.core_relations:
            attrib_list = self.global_all_attribs[tabname]
            for attrib in attrib_list:
                datatype = self.get_datatype((tabname, attrib))
                self.extract_filter_on_attrib_set(filter_attribs, query, [(tabname, attrib)], datatype)
        return filter_attribs

    def extract_filter_on_attrib_set(self, filter_attribs, query, attrib_list, datatype):
        if datatype == 'str':
            # Group mutation is not implemented for string/text/char/varchar data type
            one_attrib = attrib_list[0]
            tabname, attrib = one_attrib[0], one_attrib[1]
            self.handle_string_filter(attrib, filter_attribs, tabname, query)
        else:
            min_val_domain, max_val_domain = get_min_and_max_val(datatype)
            self.handle_filter_for_nonTextTypes(attrib_list, datatype, filter_attribs, max_val_domain, min_val_domain,
                                                query)

    def handle_filter_for_subrange(self, attrib_list, datatype, filter_attribs,
                                   max_val_domain, min_val_domain, query):
        delta, _ = get_constants_for(datatype)
        min_present = self.checkAttribValueEffect(query, get_format(datatype, min_val_domain),
                                                  attrib_list)  # True implies row
        # was still present
        max_present = self.checkAttribValueEffect(query, get_format(datatype, max_val_domain),
                                                  attrib_list)  # True implies row
        mandatory_attrib = attrib_list[0]
        tabname, attrib = mandatory_attrib[0], mandatory_attrib[1]
        if min_present and not max_present:
            val = self.get_filter_value(query, datatype,
                                        get_cast_value(datatype, min_val_domain),
                                        get_cast_value(datatype, max_val_domain), '<=', attrib_list)
            filter_attribs.append((tabname, attrib, '<=', min_val_domain, val))
        elif not min_present and max_present:
            val = self.get_filter_value(query, datatype,
                                        get_cast_value(datatype, min_val_domain),
                                        get_cast_value(datatype, max_val_domain), '>=', attrib_list)
            filter_attribs.append((tabname, attrib, '>=', val, max_val_domain))
        elif min_present and max_present:
            filter_attribs.append((tabname, attrib, 'range', min_val_domain, max_val_domain))
        else:
            if min_val_domain >= max_val_domain:
                return
            i_min, i_max = get_min_and_max_val(datatype)
            if max_val_domain == i_max or min_val_domain == i_min:
                self.handle_filter_for_nonTextTypes(attrib_list, datatype, filter_attribs,
                                                    max_val_domain, min_val_domain, query)
                return
            self.handle_filter_for_subrange(attrib_list, datatype, filter_attribs,
                                            get_val_plus_delta(datatype, max_val_domain, -1 * delta),
                                            get_val_plus_delta(datatype, min_val_domain, 1 * delta),
                                            query)

    def handle_filter_for_nonTextTypes(self, attrib_list, datatype, filter_attribs,
                                       max_val_domain, min_val_domain, query):
        if datatype in ['int', 'date', 'integer', 'number']:
            self.handle_point_filter(datatype, filter_attribs, query, attrib_list, min_val_domain, max_val_domain)
        elif datatype in ['numeric', 'float']:
            self.handle_precision_filter(filter_attribs, query, attrib_list, min_val_domain, max_val_domain)
        else:
            raise UnmasqueError(ERROR_007, "filter", f"Datatype {datatype}, is Not Handled by Current UNMASQUE...sorry!")

    def checkAttribValueEffect(self, query, val, attrib_list):
        prev_values = self.get_dmin_val_of_attrib_list(attrib_list)
        for tab_attrib in attrib_list:
            tabname, attrib = tab_attrib[0], tab_attrib[1]
            datatype = self.get_datatype((tabname, attrib))
            if datatype == 'date':
                self.connectionHelper.execute_sql(
                    [self.connectionHelper.queries.update_sql_query_tab_date_attrib_value(
                        self.get_fully_qualified_table_name(tabname), attrib, val)],
                    self.logger)
            else:
                self.connectionHelper.execute_sql(
                    [self.connectionHelper.queries.update_tab_attrib_with_value(
                        self.get_fully_qualified_table_name(tabname), attrib, val)], self.logger)
        new_result = self.app.doJob(query)
        self.revert_filter_changes_in_tabset(attrib_list, prev_values)
        return self.app.isQ_result_nonEmpty_nullfree(new_result)

    def revert_filter_changes_in_tabset(self, attrib_list, prev_val_list):
        tab_attrib_set = set()
        for i in range(len(attrib_list)):
            tab_attrib = (attrib_list[i][0], attrib_list[i][1])
            tab_attrib_set.add(tab_attrib)
            val = prev_val_list[i]
            datatype = self.get_datatype(tab_attrib)
            self.mutate_dmin_with_val(datatype, tab_attrib, val)

    def handle_precision_filter(self, filterAttribs, query, attrib_list, min_val_domain, max_val_domain):
        # min_val_domain, max_val_domain = get_min_and_max_val(datatype)
        # NUMERIC HANDLING
        # PRECISION TO BE GET FROM SCHEMA GRAPH
        min_present = self.checkAttribValueEffect(query, min_val_domain,
                                                  attrib_list)  # True implies row was still present
        max_present = self.checkAttribValueEffect(query, max_val_domain,
                                                  attrib_list)  # True implies row was still present
        mandatory_attrib = attrib_list[0]
        tabname, attrib, = mandatory_attrib[0], mandatory_attrib[1]
        dmin_val = self.global_d_plus_value[attrib]
        float_dmin_val = get_cast_value('float', dmin_val)
        # mandatory_attrib[2], mandatory_attrib[3]
        # inference based on flag_min and flag_max
        if not min_present and not max_present:
            equalto_flag = self.get_filter_value(query, 'int', float_dmin_val - .01,
                                                 float_dmin_val + .01, '=', attrib_list)
            if equalto_flag:
                filterAttribs.append((tabname, attrib, '=', float_dmin_val, float_dmin_val))
            else:
                val1 = self.get_filter_value(query, 'float', float_dmin_val, max_val_domain, '<=', attrib_list)
                val2 = self.get_filter_value(query, 'float', min_val_domain, float_dmin_val,
                                             '>=', attrib_list)
                filterAttribs.append((tabname, attrib, 'range', float(val2), float(val1)))
        elif min_present and not max_present:
            val = self.get_filter_value(query, 'float', float_dmin_val - 5, max_val_domain,
                                        '<=', attrib_list)
            val1 = self.get_filter_value(query, 'float', float(val), float(val) + 0.99, '<=', attrib_list)
            val1 = truncate_value(val1, un_precision)
            filterAttribs.append((tabname, attrib, '<=', float(min_val_domain), float(round_floor(val1, un_precision))))

        elif not min_present and max_present:
            val = self.get_filter_value(query, 'float', min_val_domain, float_dmin_val + 5,
                                        '>=', attrib_list)
            val1 = self.get_filter_value(query, 'float', float(val) - 1, val, '>=', attrib_list)
            val1 = truncate_value(val1, un_precision)
            filterAttribs.append((tabname, attrib, '>=', float(round_ceil(val1, un_precision)), float(max_val_domain)))

        elif min_present and max_present:
            # Both domain extremes satisfy: either unconstrained or a disjunctive
            # (gap) predicate (e.g. x < 100 OR x > 900). Probe candidate points to
            # find any value that violates the query (inside a gap); if found,
            # extract the contiguous satisfying interval around dmin_val as one
            # disjunct and let the disjunction loop discover other branches.
            f_min = float(get_cast_value('float', min_val_domain))
            f_max = float(get_cast_value('float', max_val_domain))
            f_d = float(float_dmin_val)
            gap_point = None

            def _probe_gap(val):
                try:
                    fv = float(val)
                except Exception:
                    return None
                if fv <= f_min or fv >= f_max:
                    return None
                try:
                    present = self.checkAttribValueEffect(query, fv, attrib_list)
                except Exception:
                    return None
                return fv if not present else None

            candidates = []
            try:
                candidates.append(get_mid_val('float', f_max, f_min))
            except Exception:
                pass
            try:
                candidates.append(get_mid_val('float', f_d, f_min))
            except Exception:
                pass
            try:
                candidates.append(get_mid_val('float', f_max, f_d))
            except Exception:
                pass
            # Geometric offsets from dmin_val to catch gaps far from midpoints.
            for step in [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 50000, 100000, 500000, 1000000]:
                candidates.extend([f_d - step, f_d + step])
            # Domain-aware fractional probes (no arbitrary fixed constants).
            try:
                span = f_max - f_min
                if span > 0:
                    for frac in [0.125, 0.25, 0.375, 0.625, 0.75, 0.875]:
                        candidates.append(f_min + span * frac)
            except Exception:
                pass

            seen = set()
            for c in candidates:
                if c is None:
                    continue
                try:
                    cf = float(c)
                except Exception:
                    continue
                # normalize key to avoid excessive duplicate probes
                key = round(cf, 6)
                if key in seen:
                    continue
                seen.add(key)
                gp = _probe_gap(cf)
                if gp is not None:
                    gap_point = gp
                    break

            if gap_point is None:
                return

            f_g = float(gap_point)
            if f_d >= f_g:
                # dmin_val in satisfying region above gap
                val_lo = self.get_filter_value(query, 'float', f_g, f_d, '>=', attrib_list)
                # upper side: search toward max only if we can bound by a bad point;
                # max domain was present, so contiguous region reaches max unless
                # another (undetected) gap exists above - treat as max in that case.
                hi = f_max
                lo = float(round_ceil(truncate_value(float(val_lo), un_precision), un_precision))
                hi_out = float(round_floor(truncate_value(float(hi), un_precision), un_precision))
                if lo <= f_min and hi_out >= f_max:
                    return
                filterAttribs.append((tabname, attrib, 'range', lo, hi_out))
            else:
                # dmin_val in satisfying region below gap
                val_hi = self.get_filter_value(query, 'float', f_d, f_g, '<=', attrib_list)
                lo = f_min
                lo_out = float(round_ceil(truncate_value(float(lo), un_precision), un_precision))
                hi_out = float(round_floor(truncate_value(float(val_hi), un_precision), un_precision))
                if lo_out <= f_min and hi_out >= f_max:
                    return
                filterAttribs.append((tabname, attrib, 'range', lo_out, hi_out))

    def get_filter_value(self, query, datatype, min_val, max_val, operator, attrib_list):
        query_front_set = set()
        for tab_attrib in attrib_list:
            tabname, attrib = tab_attrib[0], tab_attrib[1]
            query_front = self.connectionHelper.queries.update_sql_query_tab_attribs(tabname, attrib)
            query_front_set.add(query_front)
        delta, while_cut_off = get_constants_for(datatype)

        low = min_val
        high = max_val
        prev_values = self.get_dmin_val_of_attrib_list(attrib_list)

        if operator == '<=':
            while is_left_less_than_right_by_cutoff(datatype, low, high, while_cut_off):
                mid_val, new_result = self.run_app_with_mid_val(datatype, high, low, query, query_front_set)
                if mid_val == low or high == mid_val:
                    break
                if self.app.isQ_result_empty(new_result):
                    high = mid_val
                else:
                    low = mid_val
            self.revert_filter_changes_in_tabset(attrib_list, prev_values)
            return low

        if operator == '>=':
            while is_left_less_than_right_by_cutoff(datatype, low, high, while_cut_off):
                mid_val, new_result = self.run_app_with_mid_val(datatype, high, low, query, query_front_set)
                if mid_val == high or low == mid_val:
                    break
                if self.app.isQ_result_empty(new_result):
                    low = mid_val
                else:
                    high = mid_val
            self.revert_filter_changes_in_tabset(attrib_list, prev_values)
            return high

        else:  # =, i.e. datatype == 'int', date
            is_low = self.run_app_for_a_val(datatype, low, query, query_front_set)
            self.revert_filter_changes_in_tabset(attrib_list, prev_values)
            is_high = self.run_app_for_a_val(datatype, high, query, query_front_set)
            self.revert_filter_changes_in_tabset(attrib_list, prev_values)
            return not is_low and not is_high

    def run_app_for_a_val(self, datatype, low, query, query_front_set):
        for query_front in query_front_set:
            low_query = self.connectionHelper.queries.form_update_query_with_value(query_front, datatype, low)
            self.connectionHelper.execute_sql([low_query])
        new_result = self.app.doJob(query)
        return not self.app.isQ_result_empty(new_result)

    def run_app_with_mid_val(self, datatype, high, low, query, query_front_set):
        mid_val = get_mid_val(datatype, high, low)
        for q_front in query_front_set:
            update_query = self.connectionHelper.queries.form_update_query_with_value(q_front, datatype, mid_val)
            self.connectionHelper.execute_sql([update_query])
        new_result = self.app.doJob(query)
        return mid_val, new_result

        # mukul

    def handle_point_filter(self, datatype, filterAttribs, query, attrib_list, min_val_domain, max_val_domain):
        # min and max domain values (initialize based on data type)
        # PLEASE CONFIRM THAT DATE FORMAT IN DATABASE IS YYYY-MM-DD
        min_present = self.checkAttribValueEffect(query, get_format(datatype, min_val_domain),
                                                  attrib_list)  # True implies row
        # was still present
        max_present = self.checkAttribValueEffect(query, get_format(datatype, max_val_domain),
                                                  attrib_list)  # True implies row
        mandatory_attrib = attrib_list[0]
        tabname, attrib, = mandatory_attrib[0], mandatory_attrib[1]
        dmin_val = self.global_d_plus_value[attrib]
        int_dmin_val = get_cast_value(datatype, dmin_val)
        # inference based on flag_min and flag_max
        # was still present
        if not min_present and not max_present:
            equalto_flag = self.get_filter_value(query, datatype, get_val_plus_delta(datatype, int_dmin_val, -1),
                                                 get_val_plus_delta(datatype, int_dmin_val, 1),
                                                 '=', attrib_list)
            if equalto_flag:
                filterAttribs.append((tabname, attrib, '=', dmin_val, dmin_val))
            else:
                val1 = self.get_filter_value(query, datatype, int_dmin_val,
                                             get_val_plus_delta(datatype,
                                                                get_cast_value(datatype, max_val_domain), 1), '<=',
                                             attrib_list)
                val2 = self.get_filter_value(query, datatype,
                                             get_val_plus_delta(datatype, get_cast_value(datatype, min_val_domain), -1),
                                             int_dmin_val, '>=', attrib_list)
                filterAttribs.append((tabname, attrib, 'range', val2, val1))
        elif min_present and not max_present:
            val = self.get_filter_value(query, datatype, int_dmin_val,
                                        get_val_plus_delta(datatype,
                                                           get_cast_value(datatype, max_val_domain), 1), '<=',
                                        attrib_list)
            filterAttribs.append((tabname, attrib, '<=', min_val_domain, val))
        elif not min_present and max_present:
            val = self.get_filter_value(query, datatype,
                                        get_val_plus_delta(datatype, get_cast_value(datatype, min_val_domain), -1),
                                        int_dmin_val, '>=', attrib_list)
            filterAttribs.append((tabname, attrib, '>=', val, max_val_domain))

        elif min_present and max_present:
            # Both domain extremes satisfy: either unconstrained or a disjunctive
            # (gap) predicate. Probe candidates to find a value violating the
            # query; if found, extract contiguous satisfying interval around dmin_val.
            try:
                d_min_cast = get_cast_value(datatype, min_val_domain)
                d_max_cast = get_cast_value(datatype, max_val_domain)
                d_dmin_cast = get_cast_value(datatype, int_dmin_val)
            except Exception:
                return

            def _probe_gap_pt(val):
                if val is None:
                    return None
                try:
                    present = self.checkAttribValueEffect(query, get_format(datatype, val), attrib_list)
                except Exception:
                    return None
                return val if not present else None

            candidates = []
            try:
                candidates.append(get_mid_val(datatype, d_max_cast, d_min_cast))
            except Exception:
                pass
            try:
                candidates.append(get_mid_val(datatype, d_dmin_cast, d_min_cast))
            except Exception:
                pass
            try:
                candidates.append(get_mid_val(datatype, d_max_cast, d_dmin_cast))
            except Exception:
                pass
            delta, _ = get_constants_for(datatype)
            for step in [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 5000, 10000]:
                try:
                    candidates.append(get_val_plus_delta(datatype, d_dmin_cast, -step * delta))
                    candidates.append(get_val_plus_delta(datatype, d_dmin_cast, step * delta))
                except Exception:
                    pass
            # Domain-aware fractional probes (no arbitrary fixed constants).
            try:
                span = d_max_cast - d_min_cast
                if datatype == 'date':
                    span_days = span.days if hasattr(span, 'days') else int(span)
                    for frac_num, frac_den in [(1, 4), (3, 4), (1, 8), (7, 8), (1, 16), (15, 16)]:
                        offset = (span_days * frac_num) // frac_den
                        candidates.append(get_val_plus_delta(datatype, d_min_cast, offset))
                elif span is not None:
                    for frac_num, frac_den in [(1, 4), (3, 4), (1, 8), (7, 8), (1, 16), (15, 16)]:
                        offset = (span * frac_num) // frac_den if datatype in INT_TYPES else (span * frac_num / frac_den)
                        candidates.append(get_val_plus_delta(datatype, d_min_cast, offset))
            except Exception:
                pass

            gap_point = None
            seen = set()
            for c in candidates:
                try:
                    key = str(c)
                except Exception:
                    key = repr(c)
                if key in seen:
                    continue
                seen.add(key)
                gp = _probe_gap_pt(c)
                if gp is not None:
                    gap_point = gp
                    break
            if gap_point is None:
                return

            if get_cast_value(datatype, d_dmin_cast) >= get_cast_value(datatype, gap_point):
                val_lo = self.get_filter_value(query, datatype, gap_point, d_dmin_cast, '>=', attrib_list)
                hi = d_max_cast
                if val_lo == d_min_cast and hi == d_max_cast:
                    return
                filterAttribs.append((tabname, attrib, 'range', val_lo, hi))
            else:
                val_hi = self.get_filter_value(query, datatype, d_dmin_cast, gap_point, '<=', attrib_list)
                lo = d_min_cast
                if lo == d_min_cast and val_hi == d_max_cast:
                    return
                filterAttribs.append((tabname, attrib, 'range', lo, val_hi))

    def handle_string_filter(self, attrib, filterAttribs, tabname, query):
        # STRING HANDLING
        # ESCAPE CHARACTERS IN STRING REMAINING
        if self.checkStringPredicate(query, tabname, attrib):
            # returns true if there is predicate on this string attribute
            val = self.getStrFilterValue(query, tabname, attrib, str(self.global_d_plus_value[attrib]))
            val = val.strip()
            if '%' in val or '_' in val:
                filterAttribs.append((tabname, attrib, 'LIKE', val, val))
            else:
                filterAttribs.append((tabname, attrib, 'equal', val, val))

    def checkStringPredicate(self, query, tabname, attrib):
        prev_values = self.get_dmin_val_of_attrib_list([(tabname, attrib)])
        # update query
        val = 'b' if (self.global_d_plus_value[attrib] is not None and self.global_d_plus_value[attrib][
            0] == 'a') else 'a'
        val_result = self.run_updateQ_with_temp_str(attrib, query, tabname, val)
        empty_result = self.run_updateQ_with_temp_str(attrib, query, tabname, "" "")
        effect = self.app.isQ_result_empty(val_result) \
                 or self.app.isQ_result_empty(empty_result)
        # update table so that result is not empty
        self.revert_filter_changes_in_tabset([(tabname, attrib)], prev_values)
        return effect

    def getStrFilterValue(self, query, tabname, attrib, representative):
        if (tabname, attrib) in self.global_attrib_max_length.keys():
            max_length = self.global_attrib_max_length[(tabname, attrib)]
        else:
            max_length = 100000

        index = 0
        output = ""
        # currently inverted exclaimaination is being used assuming it will not be in the string
        # GET minimal string with _
        while index < len(representative):
            temp = list(representative)
            if temp[index] == 'a':
                temp[index] = 'b'
            else:
                temp[index] = 'a'
            temp = ''.join(temp)
            new_result = self.run_updateQ_with_temp_str(attrib, query, tabname, temp)
            if not self.app.isQ_result_empty(new_result):
                temp = copy.deepcopy(representative)
                temp = temp[:index] + temp[index + 1:]
                new_result = self.run_updateQ_with_temp_str(attrib, query, tabname, temp)
                if not self.app.isQ_result_empty(new_result):
                    representative = representative[:index] + representative[index + 1:]
                else:
                    output = output + "_"
                    representative = list(representative)
                    representative[index] = u"\u00A1"
                    representative = ''.join(representative)
                    index = index + 1
            else:
                output = output + representative[index]
                index = index + 1
        if output == '':
            return output
        # GET % positions
        index = 0
        representative = copy.deepcopy(output)
        if len(representative) < max_length:
            output = ""
            while index < len(representative):
                temp = list(representative)
                if temp[index] == 'a':
                    temp.insert(index, 'b')
                else:
                    temp.insert(index, 'a')
                temp = ''.join(temp)
                new_result = self.run_updateQ_with_temp_str(attrib, query, tabname, temp)
                if not self.app.isQ_result_empty(new_result):
                    output = output + '%'
                output = output + representative[index]
                index = index + 1
            temp = list(representative)
            if temp[index - 1] == 'a':
                temp.append('b')
            else:
                temp.append('a')
            temp = ''.join(temp)
            new_result = self.run_updateQ_with_temp_str(attrib, query, tabname, temp)
            if not self.app.isQ_result_empty(new_result):
                output = output + '%'
        return output

    def run_updateQ_with_temp_str(self, attrib, query, tabname, temp):
        prev_values = self.get_dmin_val_of_attrib_list([(tabname, attrib)])
        up_query = self.connectionHelper.queries.update_tab_attrib_with_quoted_value(
            self.get_fully_qualified_table_name(tabname), attrib, temp)
        self.connectionHelper.execute_sql([up_query])
        new_result = self.app.doJob(query)
        self.revert_filter_changes_in_tabset([(tabname, attrib)], prev_values)
        return new_result