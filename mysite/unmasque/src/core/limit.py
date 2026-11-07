import ast
import copy
import itertools

import frozenlist as frozenlist

from .dataclass.genPipeline_context import GenPipelineContext
from .dataclass.pgao_context import PGAOcontext
from ...src.core.abstract.GenerationPipeLineBase import GenerationPipeLineBase, get_boundary_value
from ..util.constants import NON_TEXT_TYPES
from ...src.util.utils import get_dummy_val_for, get_val_plus_delta, get_format, get_char


class Limit(GenerationPipeLineBase):
    def __init__(self, connectionHelper, genPipelineCtx: GenPipelineContext,
                 genCtx: PGAOcontext):
        super().__init__(connectionHelper, "Limit", genPipelineCtx)
        self.limit = None
        self.global_groupby_attributes = genCtx.group_by_attrib
        self.joined_attrib_valDict = {}
        self.no_rows = self.connectionHelper.config.limit_limit
        self.rmin_card = genCtx.projection
        self.__dmin_cache = {}
        self.__join_edges_by_attrib = self.__build_join_edge_index()
        self.__attrib_to_table = self.__build_attrib_table_index()
        self.__filter_in_values = self.__build_filter_in_value_index()
        self.__joined_attrib_set = set(self.joined_attribs or [])

    def doExtractJob(self, query):
        result = self.doLimitExtractJob(query)
        self.do_init()
        return result

    def doLimitExtractJob(self, query):
        grouping_attribute_values = {}
        pre_assignment = self.__get_pre_assignment()
        gb_tab_attribs = [(self.__find_table_for_attrib(attrib), attrib)
                          for attrib in self.global_groupby_attributes]
        gb_tab_attrib_set = set(gb_tab_attribs)

        total_combinations = 1
        self.__decide_number_of_rows(gb_tab_attribs, grouping_attribute_values, pre_assignment, total_combinations)

        gen_dict = {}

        for table in self.core_relations:
            attrib_list = self.global_all_attribs[table]
            attrib_list_str = ",".join(attrib_list)
            att_order = f"({attrib_list_str})"
            insertion_plan = self.__build_insertion_plan(attrib_list, gb_tab_attrib_set,
                                                         grouping_attribute_values, table)
            insert_rows = []
            for k in range(self.no_rows):
                self.__determine_k_insert_rows(insertion_plan, grouping_attribute_values, insert_rows, k, table)
            self.insert_attrib_vals_into_table_many(att_order, attrib_list, insert_rows, table, insert_logger=False)
            gen_dict[table] = insert_rows

            new_result = self.app.doJob(query)
            if not self.app.isQ_result_empty(new_result):
                """                 
                ideally dmin at the start of proj module should produce 2 row result. header + 1 row data
                but, union + outer join may cause extra invalid data.
                all of them cannot be discarded simply due to having NULL values
                So, assuming ideal data at proj module start, calculating the valid rows in other modules
                """
                fresh_result_card = len(new_result) - self.rmin_card + 2
                if 4 <= fresh_result_card <= self.no_rows:
                    if self.limit is not None and self.limit == fresh_result_card - 1:
                        self.limit = fresh_result_card - 1  # excluding the header column
                        self.logger.debug(f"Finalized Limit {self.limit}")
                        break
                    else:
                        self.limit = fresh_result_card - 1  # excluding the header column
                        self.logger.debug(f"Limit {self.limit}")
                else:
                    if self.limit is not None:
                        self.limit = None
                        self.logger.debug(f"Result is growing. Limit may be larger than {self.no_rows}")
                        break
        return True

    def __build_insertion_plan(self, attrib_list_inner, gb_tab_attrib_set, grouping_attribute_values,
                               tabname_inner):
        insertion_plan = []
        for attrib_inner in attrib_list_inner:
            datatype = self.get_datatype((tabname_inner, attrib_inner))
            if attrib_inner in grouping_attribute_values:
                insertion_plan.append(('group', attrib_inner))
            elif attrib_inner not in self.__joined_attrib_set \
                    and (tabname_inner, attrib_inner) not in gb_tab_attrib_set:
                insertion_plan.append(('dmin', self.__get_dmin_value(attrib_inner, tabname_inner)))
            elif datatype in NON_TEXT_TYPES:
                insertion_plan.append(
                    ('non_text', attrib_inner, datatype,
                     self.__join_edges_by_attrib.get(attrib_inner, []),
                     self.get_s_val(attrib_inner, tabname_inner),
                     self.__get_filter_upper_bound(attrib_inner, tabname_inner)))
            else:
                filter_val = None
                if (tabname_inner, attrib_inner) in self.filter_attrib_dict:
                    filter_val = self.get_s_val_for_textType(attrib_inner, tabname_inner)
                insertion_plan.append(('text', attrib_inner, filter_val))
        return insertion_plan

    def __determine_k_insert_rows(self, insertion_plan, grouping_attribute_values, insert_rows, k, tabname_inner):
        insert_values = []
        for entry in insertion_plan:
            insertion_kind = entry[0]
            if insertion_kind == 'group':
                insert_values.append(grouping_attribute_values[entry[1]][k])
            elif insertion_kind == 'dmin':
                insert_values.append(entry[1])
            elif insertion_kind == 'non_text':
                _, attrib_inner, datatype, edge_keys, s_val, upper_bound = entry
                self.insert_non_text_attrib(datatype, attrib_inner, insert_values, k, tabname_inner,
                                            edge_keys, s_val, upper_bound)
            else:
                _, attrib_inner, filter_val = entry
                self.insert_text_attrib(attrib_inner, insert_values, k, tabname_inner, filter_val)
        insert_rows.append(tuple(insert_values))

    def __get_dmin_value(self, attrib_inner, tabname_inner):
        key = (tabname_inner, attrib_inner)
        if key not in self.__dmin_cache:
            self.__dmin_cache[key] = self.get_dmin_val(attrib_inner, tabname_inner)
        return self.__dmin_cache[key]

    def __get_filter_upper_bound(self, attrib_inner, tabname_inner):
        key = (tabname_inner, attrib_inner)
        if key in self.filter_attrib_dict:
            return get_boundary_value(self.filter_attrib_dict[key][1], is_ub=True)
        return None

    def __build_join_edge_index(self):
        join_edge_index = {}
        for edge in self.global_join_graph or []:
            edge_key = frozenlist.FrozenList(edge)
            edge_key.freeze()
            for attrib in edge:
                join_edge_index.setdefault(attrib, []).append(edge_key)
        return join_edge_index

    def __build_attrib_table_index(self):
        attrib_table_index = {}
        for table, attribs in self.global_all_attribs.items():
            for attrib in attribs:
                attrib_table_index.setdefault(attrib, table)
        return attrib_table_index

    def __build_filter_in_value_index(self):
        filter_in_value_index = {}
        for in_pred in self.filter_in_predicates or []:
            filter_in_value_index.setdefault((in_pred[0], in_pred[1]), []).append(in_pred[3])
        return filter_in_value_index

    def __find_table_for_attrib(self, attrib_inner):
        if attrib_inner in self.__attrib_to_table:
            return self.__attrib_to_table[attrib_inner]
        return self.find_tabname_for_given_attrib(attrib_inner)

    def __decide_number_of_rows(self, gb_tab_attribs, grouping_attribute_values, pre_assignment, total_combinations):
        if pre_assignment:
            # GET LIMITS FOR ALL GROUPBY ATTRIBUTES
            group_lists = []
            for elt in gb_tab_attribs:
                temp = []
                if elt not in self.filter_attrib_dict.keys():
                    pre_assignment = False
                    break
                datatype = self.get_datatype(elt)
                if datatype in NON_TEXT_TYPES:
                    tot_values = self.__compute_total_values(datatype, elt, total_combinations)
                    self.__get_temp_total_values(datatype, elt, temp, tot_values)
                else:
                    if '%' in self.filter_attrib_dict[elt] or '_' in self.filter_attrib_dict[elt]:
                        pre_assignment = False
                        break
                    else:
                        temp = [self.filter_attrib_dict[elt]]
                total_combinations = total_combinations * len(temp)
                group_lists.append(copy.deepcopy(temp))

            # CREATE DIFFERENT PERMUTATIONS OF GROUPBY COLUMNS VALUE ASSIGNMENTS HERE
            if pre_assignment:
                combo_values = list(itertools.product(*group_lists))
                for elt in self.global_groupby_attributes:
                    grouping_attribute_values[elt] = []
                for elt in combo_values:
                    temp = list(elt)
                    for (val1, val2) in zip(self.global_groupby_attributes, temp):
                        grouping_attribute_values[val1].append(val2)
        if pre_assignment:
            self.no_rows = min(self.no_rows, total_combinations)

    def __get_temp_total_values(self, datatype, elt, temp, tot_values):
        if datatype == 'date':
            for k in range(tot_values):
                date_val = get_val_plus_delta('date', self.filter_attrib_dict[elt][0], k)
                temp.append(ast.literal_eval(get_format('date', date_val)))
        else:
            lb = get_boundary_value(self.filter_attrib_dict[elt][0], is_ub=False)
            for k in range(tot_values):
                temp.append(lb + k)

    def __compute_total_values(self, datatype, elt, total_combinations):
        tot_values = 0
        for value_range in self.__filter_in_values.get(elt, []):
            for v in value_range:
                if not isinstance(v, tuple):
                    tot_values += 1
                else:
                    tot_values += v[-1] - v[0]
        if not tot_values:
            if datatype == 'date':
                tot_values = (self.filter_attrib_dict[elt][1] - self.filter_attrib_dict[elt][0]).days + 1
            else:
                tot_values = self.filter_attrib_dict[elt][1] - self.filter_attrib_dict[elt][0] + 1
        if (total_combinations * tot_values) > self.no_rows:
            i = 1
            while (total_combinations * i) < self.no_rows + 1 and i < tot_values:
                i = i + 1
            tot_values = i
        return tot_values

    def insert_text_attrib(self, attrib_inner, insert_values, k, tabname_inner, filter_val=None):
        char_val = get_char(get_val_plus_delta('char', get_dummy_val_for('char'), k))  # why need unique values?
        if filter_val is not None:
            temp = copy.deepcopy(filter_val)
            if '_' in filter_val:
                insert_values.append(temp.replace('_', char_val))
            else:
                insert_values.append(temp.replace('%', char_val, 1))
            insert_values[-1].replace('%', '')
        else:
            insert_values.append(char_val)

    def insert_non_text_attrib(self, datatype, attrib_inner, insert_values, k, tabname_inner,
                               edge_keys, s_val, upper_bound):
        for edge_key in edge_keys:
            if edge_key in self.joined_attrib_valDict \
                    and k < len(self.joined_attrib_valDict[edge_key]):
                s_val_plus_k = self.joined_attrib_valDict[edge_key][k]
                insert_values.append(ast.literal_eval(get_format(datatype, s_val_plus_k)))
                return

        if datatype != 'date':
            datatype = 'int'
        # check for filter (#MORE PRECISION CAN BE ADDED FOR NUMERIC#)
        s_val_plus_k = get_val_plus_delta(datatype, s_val, k)
        if upper_bound is not None:
            s_val_plus_k = min(s_val_plus_k, upper_bound)
        insert_values.append(ast.literal_eval(get_format(datatype, s_val_plus_k)))
        for edge_key in edge_keys:
            if edge_key in self.joined_attrib_valDict:
                self.joined_attrib_valDict[edge_key].append(s_val_plus_k)
            else:
                self.joined_attrib_valDict[edge_key] = [s_val_plus_k]

    def __get_pre_assignment(self):
        pre_assignment = True
        for elt in self.global_groupby_attributes:
            if elt in self.__joined_attrib_set:
                pre_assignment = False
                break
        if not self.global_groupby_attributes:
            pre_assignment = False
        return pre_assignment
