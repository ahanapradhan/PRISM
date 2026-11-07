from types import SimpleNamespace

from mysite.unmasque.src.core.dataclass.genPipeline_context import merge_overlapping_ranges
from mysite.unmasque.src.pipeline.fragments.DisjunctionPipeLine import DisjunctionPipeLine


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class _FilterExtractor:
    def get_datatype(self, tab_attrib):
        return 'numeric' if tab_attrib[1] == 'c_acctbal' else 'str'


class _DisjunctionPipeline(DisjunctionPipeLine):
    def __init__(self, returned_predicates, detect_or=True):
        self.OR_CUTOFF = 1000
        self.logger = _NullLogger()
        self.connectionHelper = SimpleNamespace(config=SimpleNamespace(detect_or=detect_or))
        self.filter_extractor = _FilterExtractor()
        self.state = []
        self.all_sizes = {}
        self.returned_predicates = returned_predicates
        self.mutation_calls = 0

    def _mutation_pipeline(self, core_relations, query, time_profile, restore_details=None):
        self.mutation_calls += 1
        return True, time_profile

    def _DisjunctionPipeLine__get_predicates_in_action(self):
        return self.returned_predicates

    def process(self, query):
        pass

    def doJob(self, query, qe=None):
        pass

    def verify_correctness(self, query, result):
        pass

    def extract(self, query):
        pass


def test_non_disjunctive_range_terminates_without_new_predicate():
    initial = ('customer', 'c_acctbal', 'range', 9000, 9559.94)
    pipeline = _DisjunctionPipeline([('customer', 'c_acctbal', 'range', 9000, 9571.61)])
    check, _ = pipeline._extract_disjunction([initial], ['customer'], 'query', None)
    assert check
    assert pipeline.or_predicates == [(initial,)]
    assert pipeline.mutation_calls == 1


def test_disjoint_or_values_are_kept():
    initial = ('lineitem', 'l_shipmode', 'equal', 'AIR', 'AIR')
    alternative = ('lineitem', 'l_shipmode', 'equal', 'TRUCK', 'TRUCK')
    pipeline = _DisjunctionPipeline([alternative])
    check, _ = pipeline._extract_disjunction([initial], ['lineitem'], 'query', None)
    assert check
    assert pipeline.or_predicates == [(initial, alternative)]
    assert pipeline.mutation_calls == 2


def test_merge_overlapping_ranges():
    assert merge_overlapping_ranges([(1, 5), (4, 8), (7, 10)]) == [(1, 10)]
    assert merge_overlapping_ranges([(1, 5), (7, 10)]) == [(1, 5), (7, 10)]
