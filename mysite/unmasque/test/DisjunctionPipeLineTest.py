from types import SimpleNamespace

import pytest

from mysite.unmasque.src.core.dataclass.genPipeline_context import GenPipelineContext, merge_overlapping_ranges
from mysite.unmasque.src.pipeline.fragments.DisjunctionPipeLine import DisjunctionPipeLine
from mysite.unmasque.src.util.error_handling import UnmasqueError


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
        if callable(self.returned_predicates):
            return self.returned_predicates(self.mutation_calls)
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


def test_foreign_attribute_is_not_appended_to_existing_column():
    initial = ('customer', 'c_acctbal', 'range', 9000, 9559.94)
    foreign = ('lineitem', 'l_shipmode', 'equal', 'TRUCK', 'TRUCK')
    pipeline = _DisjunctionPipeline([foreign])
    check, _ = pipeline._extract_disjunction([initial], ['customer', 'lineitem'], 'query', None)
    assert check
    assert pipeline.or_predicates == [(initial,), (foreign,)]


def test_foreign_attribute_does_not_replace_same_attribute_candidate():
    initial = ('customer', 'c_acctbal', 'range', 9000, 9559.94)
    alternative = ('customer', 'c_acctbal', 'range', 10000, 11000)
    foreign = ('lineitem', 'l_shipmode', 'equal', 'TRUCK', 'TRUCK')
    pipeline = _DisjunctionPipeline([foreign, alternative])
    check, _ = pipeline._extract_disjunction([initial], ['customer', 'lineitem'], 'query', None)
    assert check
    assert pipeline.or_predicates == [(initial, alternative), (foreign,)]


def test_discovered_attribute_is_probed_for_additional_values():
    initial = ('customer', 'c_acctbal', 'range', 9000, 9559.94)
    truck = ('lineitem', 'l_shipmode', 'equal', 'TRUCK', 'TRUCK')
    air = ('lineitem', 'l_shipmode', 'equal', 'AIR', 'AIR')

    def actions(mutation_calls):
        return [air] if mutation_calls >= 3 else [truck]

    pipeline = _DisjunctionPipeline(actions)
    check, _ = pipeline._extract_disjunction([initial], ['customer', 'lineitem'], 'query', None)
    assert check
    assert pipeline.or_predicates == [(initial,), (truck, air)]


def test_or_predicate_columns_never_mix_attributes():
    initial = ('customer', 'c_acctbal', 'range', 9000, 9559.94)
    foreign = ('lineitem', 'l_shipmode', 'equal', 'TRUCK', 'TRUCK')
    pipeline = _DisjunctionPipeline([foreign])
    pipeline._extract_disjunction([initial], ['customer', 'lineitem'], 'query', None)
    for column in pipeline.or_predicates:
        tab_attribs = {(pred[0], pred[1]) for pred in column if pred}
        assert len(tab_attribs) == 1


def test_error_007_details_include_offending_attributes():
    context = GenPipelineContext.__new__(GenPipelineContext)
    context._GenPipelineContext__or_predicates = [
        (
            ('customer', 'c_acctbal', 'range', 9000, 9559.94),
            ('lineitem', 'l_shipmode', 'equal', 'TRUCK', 'TRUCK'),
        )
    ]
    context.arithmetic_filters = []
    with pytest.raises(UnmasqueError) as error:
        context._GenPipelineContext__generate_arithmetic_conjunctive_disjunctions()
    assert 'customer' in str(error.value.info)
    assert 'c_acctbal' in str(error.value.info)
    assert 'lineitem' in str(error.value.info)
    assert 'l_shipmode' in str(error.value.info)
