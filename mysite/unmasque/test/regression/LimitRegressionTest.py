import logging
import unittest

from ...src.core.limit import Limit


class _ScriptedApp:
    """Executable stub returning a pre-scripted result for every doJob call.

    Each result is a list whose first element is the header row, so a result
    with ``n`` data rows has length ``n + 1``.
    """

    def __init__(self, result_sizes):
        self._sizes = list(result_sizes)
        self.calls = 0

    def doJob(self, query):
        size = self._sizes[self.calls]
        self.calls += 1
        return [("header",)] + [("row",)] * (size - 1)

    @staticmethod
    def isQ_result_empty(result):
        return len(result) <= 1


def _make_limit(core_relations, result_sizes, rmin_card=2, no_rows=1000):
    """Build a Limit instance with all database/insertion work stubbed out."""
    lm = object.__new__(Limit)
    lm.core_relations = list(core_relations)
    lm.global_groupby_attributes = []
    lm.joined_attribs = []
    lm.global_all_attribs = {table: ["dummy"] for table in core_relations}
    lm.joined_attrib_valDict = {}
    lm.no_rows = no_rows
    lm.rmin_card = rmin_card
    lm.limit = None
    lm.filter_attrib_dict = {}
    lm.filter_in_predicates = []
    lm.global_join_graph = []
    lm.app = _ScriptedApp(result_sizes)
    lm.logger = logging.getLogger(__name__)

    # No real inserts are needed; the cardinalities come from _ScriptedApp.
    lm.insert_attrib_vals_into_table = lambda *args, **kwargs: None
    lm._Limit__determine_k_insert_rows = lambda *args, **kwargs: None
    return lm


class LimitPlateauRegressionTest(unittest.TestCase):
    """Regression tests for finalizing LIMIT before all relations are populated.

    MQ2 (``LIMIT 100``) intermittently extracted ``LIMIT 3`` because the result
    cardinality temporarily plateaued at 3 rows while only some of the five
    core relations had been filled.  The plateau is only meaningful once every
    core relation has been populated.
    """

    def test_mq2_limit_is_not_finalized_on_an_intermediate_plateau(self):
        # Order observed in the failing run: the plateau at 4 (= 3 rows) happens
        # on 'part' while 'partsupp' is still to be populated.
        lm = _make_limit(
            core_relations=["nation", "supplier", "region", "part", "partsupp"],
            result_sizes=[2, 2, 4, 4, 101],
        )

        lm.doLimitExtractJob("SELECT ... LIMIT 100")

        self.assertEqual(100, lm.limit)

    def test_mq2_limit_is_found_regardless_of_relation_order(self):
        # Order observed in the succeeding run; the final relation pushes the
        # result to 100 data rows.
        lm = _make_limit(
            core_relations=["nation", "part", "partsupp", "region", "supplier"],
            result_sizes=[2, 2, 4, 4, 101],
        )

        lm.doLimitExtractJob("SELECT ... LIMIT 100")

        self.assertEqual(100, lm.limit)

    def test_genuine_plateau_after_all_relations_is_still_finalized(self):
        # Every relation is populated and the result genuinely stops at 3 rows.
        lm = _make_limit(
            core_relations=["nation", "supplier", "region", "part", "partsupp"],
            result_sizes=[2, 2, 4, 4, 4],
        )

        lm.doLimitExtractJob("SELECT ... LIMIT 3")

        self.assertEqual(3, lm.limit)


if __name__ == "__main__":
    unittest.main()
