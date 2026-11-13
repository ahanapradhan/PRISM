import copy

from tabulate import tabulate


def create_zero_time_profile():
    return ElapsedTime()


class ElapsedTime:
    clause_keys = ["From Clause:",
                   "Union:",
                   "Restore DB:",
                   "Correlated Sampling:",
                   "View Minimization:",
                   "Where Clause:",
                   "Projection:",
                   "Group BY:",
                   "Aggregation:",
                   "Order by:",
                   "Limit:",
                   "Outer Join:",
                   "NEP: ",
                   "Result\n Comparator:"]

    def __init__(self):
        self.table_string = ''
        self.app_db_restore = 0
        self.t_db_restore = 0

        self.t_sampling = 0
        self.t_view_min = 0
        self.t_where_clause = 0
        self.t_projection = 0
        self.t_groupby = 0
        self.t_aggregate = 0
        self.t_orderby = 0
        self.t_limit = 0
        self.t_outer_join = 0
        self.t_nep = 0
        self.t_union = 0
        self.t_from_clause = 0
        self.t_result_comp = 0
        self.t_init = 0
        self.t_total = 0
        self.display_string = ''

        self.app_sampling = 0
        self.app_view_min = 0
        self.app_where_clause = 0
        self.app_projection = 0
        self.app_groupby = 0
        self.app_aggregate = 0
        self.app_orderby = 0
        self.app_limit = 0
        self.app_outer_join = 0
        self.app_nep = 0
        self.app_union = 0
        self.app_from_clause = 0
        self.app_result_comp = 0
        self.app_init = 0
        self.app_total = 0

    def update_for_init(self, t_u, c_app):
        """Pre-extraction setup: working schema, base-table backup, sizes, scale-down.

        Kept out of the per-module table: it is one-time setup, not PRISM extraction.
        """
        self.t_init += t_u
        self.app_init += c_app

    def update_for_from_clause(self, t_u, c_app):
        self.t_from_clause += t_u
        self.app_from_clause += c_app

    def update_for_union(self, t_u, c_app):
        self.t_union += t_u
        self.app_union += c_app

    def update_for_result_comparator(self, t_u, c_app):
        self.t_result_comp += t_u
        self.app_result_comp += c_app

    def update_for_where_clause(self, t_u, c_app):
        self.t_where_clause += t_u
        self.app_where_clause += c_app

    def update_for_projection(self, t_u, c_app):
        self.t_projection += t_u
        self.app_projection += c_app

    def update_for_group_by(self, t_u, c_app):
        self.t_groupby += t_u
        self.app_groupby += c_app

    def update_for_aggregate(self, t_u, c_app):
        self.t_aggregate += t_u
        self.app_aggregate += c_app

    def update_for_order_by(self, t_u, c_app):
        self.t_orderby += t_u
        self.app_orderby += c_app

    def update_for_limit(self, t_u, c_app):
        self.t_limit += t_u
        self.app_limit += c_app

    def update_for_cs2(self, t_u, c_app):
        self.t_sampling += t_u
        self.app_sampling += c_app

    def update_for_db_restore(self, t_u, c_app):
        self.t_db_restore += t_u
        self.app_db_restore += c_app

    def update_for_view_minimization(self, t_u, c_app):
        self.t_view_min += t_u
        self.app_view_min += c_app

    def update_for_nep(self, t_u, c_app):
        self.t_nep += t_u
        self.app_nep += c_app

    def update_for_outer_join(self, t_u, c_app):
        self.t_outer_join += t_u
        self.app_outer_join += c_app

    def update_for_app(self, t_u):
        self.app_total += t_u

    def update_for_total_time(self, t_u):
        self.t_total += t_u

    def update(self, other_profile):
        self.t_from_clause += other_profile.t_from_clause
        self.t_union += other_profile.t_union
        self.t_sampling += other_profile.t_sampling
        self.t_view_min += other_profile.t_view_min
        self.t_where_clause += other_profile.t_where_clause
        self.t_projection += other_profile.t_projection
        self.t_groupby += other_profile.t_groupby
        self.t_aggregate += other_profile.t_aggregate
        self.t_orderby += other_profile.t_orderby
        self.t_limit += other_profile.t_limit
        self.t_outer_join += other_profile.t_outer_join
        self.t_nep += other_profile.t_nep
        self.t_result_comp += other_profile.t_result_comp
        self.t_db_restore += other_profile.t_db_restore
        self.t_init += other_profile.t_init
        # t_total is an end-to-end wall-clock measurement made once in doJob();
        # merging sub-profiles must not add a second total.

        self.app_total += other_profile.app_total
        self.app_from_clause += other_profile.app_from_clause
        self.app_union += other_profile.app_union
        self.app_sampling += other_profile.app_sampling
        self.app_view_min += other_profile.app_view_min
        self.app_where_clause += other_profile.app_where_clause
        self.app_projection += other_profile.app_projection
        self.app_groupby += other_profile.app_groupby
        self.app_aggregate += other_profile.app_aggregate
        self.app_orderby += other_profile.app_orderby
        self.app_limit += other_profile.app_limit
        self.app_outer_join += other_profile.app_outer_join
        self.app_nep += other_profile.app_nep
        self.app_result_comp += other_profile.app_result_comp
        self.app_db_restore += other_profile.app_db_restore
        self.app_init += other_profile.app_init

    def print(self):
        max_len = len(max(self.clause_keys, key=len)) + 1
        keys_tabs = []
        for key in self.clause_keys:
            tabs = max_len - len(key)
            keys_tabs.append(tabs)

        times = self.get_times()
        app_calls = self.get_app_calls()

        self.display_string += "\n--------------Extraction Time per Module in the Pipeline------------------:"
        i = 0
        while i < len(self.clause_keys):
            self.display_string += str("\n" +
                                       self.clause_keys[i] + " " + ' ' * (
                                               max_len - len(self.clause_keys[i])) + " " +
                                       str(round(times[i], 2)) + " s.")
            i += 1
        self.display_string += str("\nPRISM-total: " + ' ' * (max_len - len("PRISM-total:")) + " " +
                                   str(round(self.get_prism_total(), 2)) + " s.")
        self.display_string += str("\nWall-clock: " + ' ' * (max_len - len("Wall-clock:")) + " " +
                                   str(round(self.get_wall_clock_total(), 2)) + " s.")

        # Pre-extraction setup (working schema, backup, row counts, scale-down)
        # is one-time setup, not PRISM extraction. Report it on its own line
        # instead of adding a table row.
        if self.t_init:
            print(f"Pre-extraction init/backup: {self.t_init:.2f} s "
                  f"(included in Wall-clock, excluded from PRISM-total).")

        # print(self.display_string)
        pp_tab = zip(self.clause_keys, times, app_calls)

        table = list(pp_tab)
        table.append(["PRISM-total:", round(self.get_prism_total(), 2), self.app_total])
        table.append(["Wall-clock:",
                      round(self.get_wall_clock_total(), 2),
                      self.app_total + self.app_init])
        header = ["Step", "Time (s)", "App Calls"]
        table.insert(0, header)
        print(tabulate(table, headers='firstrow', tablefmt='fancy_grid'))

    def get_json_display_string(self):
        self.print()
        ds = copy.deepcopy(self.display_string)
        ds = ds.replace("\n", "<br>")
        return ds

    def get_table_display_string(self):
        times = self.get_times()
        app = self.get_app_calls()
        self.table_string = '''<table class="min_tab">'''
        self.table_string += '''<tr><th>Stage</th><th>Time Taken (s)</th><th>Exec Called</th></tr>'''
        for key, time_taken, exec_called in zip(self.clause_keys, times, app):
            self.table_string += ('<tr><td>' + key + '</td><td>' + str(time_taken) +
                                  '</td><td>' + str(exec_called) + '</td></tr>')
        self.table_string += ('<tr><td>PRISM-total:</td><td>' + str(round(self.get_prism_total(), 2)) +
                              '</td><td>' + str(self.app_total) + '</td></tr>')
        self.table_string += ('<tr><td>Wall-clock:</td><td>' + str(round(self.get_wall_clock_total(), 2)) +
                              '</td><td>' + str(self.app_total + self.app_init) + '</td></tr>')
        self.table_string += '</table>'
        return self.table_string

    def get_prism_total(self):
        """Time spent by PRISM extraction, excluding pre-extraction init/backup."""
        if self.t_total:
            return max(self.t_total - self.t_init, 0.0)
        return sum(self.get_times())

    def get_wall_clock_total(self):
        """End-to-end wall-clock time, including pre-extraction init/backup."""
        if self.t_total:
            return self.t_total
        return self.get_prism_total() + self.t_init

    def get_times(self):
        times = [round(entry, 2) for entry in [self.t_from_clause,
                                               self.t_union,
                                               self.t_db_restore,
                                               self.t_sampling,
                                               self.t_view_min,
                                               self.t_where_clause,
                                               self.t_projection,
                                               self.t_groupby,
                                               self.t_aggregate,
                                               self.t_orderby,
                                               self.t_limit,
                                               self.t_outer_join,
                                               self.t_nep,
                                               self.t_result_comp]]

        return times

    def get_app_calls(self):
        apps = [self.app_from_clause,
                self.app_union,
                self.app_db_restore,
                self.app_sampling,
                self.app_view_min,
                self.app_where_clause,
                self.app_projection,
                self.app_groupby,
                self.app_aggregate,
                self.app_orderby,
                self.app_limit,
                self.app_outer_join,
                self.app_nep,
                self.app_result_comp]
        return apps
