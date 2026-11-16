from ....src.core.executables.executable import Executable


class ZeroResultExecutable(Executable):
    def __init__(self, connectionHelper):
        super().__init__(connectionHelper, "Zero_Result_Executable")

    def is_attrib_all_null(self, Res, attrib):
        return self.isQ_result_empty(Res)

    def get_attrib_val(self, Res, attrib_idx):
        return Res[1][attrib_idx]

    def isQ_result_no_full_nullfree_row(self, Res):
        return self.isQ_result_empty(Res)

    def isQ_result_nonEmpty_nullfree(self, Res):
        return not self.isQ_result_empty(Res)

    def isQ_result_empty(self, Res):
        if len(Res) == 2:
            data = Res[-1]
            check = all(val in [0, '0', None, 'None'] for val in data)
            if check:
                return True
        return super().isQ_result_empty(Res)

    def isQ_result_has_no_data(self, Res):
        return self.isQ_result_empty(Res)

    def isQ_result_all_null(self, Res):
        return self.isQ_result_empty(Res)

    def isQ_result_has_some_data(self, Res):
        return not self.isQ_result_empty(Res)

    def is_query_result_no_full_nullfree_row(self, query):
        q = self._strip_query_terminator(query)
        # LIMIT 2 keeps the "exactly one all-zero/all-None row means empty"
        # rule of isQ_result_empty detectable while transferring at most 2 rows.
        res = self.doJob(f"SELECT q.* FROM ({q}) AS q LIMIT 2;")
        if not self.done or not isinstance(res, list):
            return False
        return self.isQ_result_empty(res)
