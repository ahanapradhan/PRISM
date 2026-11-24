from datetime import date

from ...src.core.aoa import InequalityPredicate
from ...src.pipeline.ExtractionPipeLine import ExtractionPipeLine


class _Stub:
    pass


def _bare_aoa():
    """Create an InequalityPredicate without running its DB-backed constructor."""
    return object.__new__(InequalityPredicate)


def test_absorbed_bound_is_not_rediscovered_as_dormant():
    aoa = _bare_aoa()
    aoa._InequalityPredicate__absorbed_LBs = {
        ('lineitem', 'l_receiptdate'): [date(1993, 9, 27)]
    }
    aoa._InequalityPredicate__absorbed_UBs = {}

    edge_set = []
    aoa._InequalityPredicate__extract_dormant_concrete_bound(
        edge_set, [], ('lineitem', 'l_receiptdate'), 'date', 'SELECT 1', False)

    assert edge_set == []


def test_probe_reset_restores_dmin_values():
    filter_extractor = _Stub()
    filter_extractor.global_min_instance_dict = {
        'lineitem': (['l_receiptdate', 'l_commitdate'],
                     (date(1993, 9, 27), date(1993, 10, 14)))
    }
    filter_extractor.global_d_plus_value = {
        'l_receiptdate': date(2000, 1, 1),
        'l_commitdate': date(2000, 1, 1),
    }

    aoa = _bare_aoa()
    aoa.filter_extractor = filter_extractor
    aoa.global_d_plus_value = dict(filter_extractor.global_d_plus_value)
    restored = []
    aoa.restore_d_min_from_dict = lambda: restored.append(True)

    aoa._InequalityPredicate__reset_dmin_state_for_probe()

    assert restored == [True]
    assert filter_extractor.global_d_plus_value == {
        'l_receiptdate': date(1993, 9, 27),
        'l_commitdate': date(1993, 10, 14),
    }
    assert aoa.global_d_plus_value == filter_extractor.global_d_plus_value


def test_completed_aoa_state_survives_disjunction_probes():
    original_aoa = _Stub()
    original_aoa.filter_extractor = _Stub()
    original_aoa.global_min_instance_dict = {}
    original_aoa_restores = []
    original_aoa.restore_d_min_from_dict = lambda: original_aoa_restores.append(True)

    original_filter = _Stub()
    original_equi_join = _Stub()
    original_dmin = {'lineitem': (['l_receiptdate'], (date(1993, 9, 27),))}

    pipeline = object.__new__(ExtractionPipeLine)
    pipeline.aoa = original_aoa
    pipeline.filter_extractor = original_filter
    pipeline.equi_join = original_equi_join
    pipeline.global_min_instance_dict = original_dmin

    snapshot = pipeline._ExtractionPipeLine__snapshot_aoa_state()

    # Simulate OR probes replacing the mutation-pipeline state.
    pipeline.aoa = _Stub()
    pipeline.filter_extractor = _Stub()
    pipeline.equi_join = _Stub()
    pipeline.global_min_instance_dict = {'lineitem': (['l_receiptdate'], (date(2000, 1, 1),))}

    pipeline._ExtractionPipeLine__restore_aoa_state(snapshot)

    assert pipeline.aoa is original_aoa
    assert pipeline.filter_extractor is original_filter
    assert pipeline.equi_join is original_equi_join
    assert pipeline.global_min_instance_dict == original_dmin
    assert original_aoa.filter_extractor is original_filter
    assert original_aoa.global_min_instance_dict == original_dmin
    assert original_aoa_restores == [True]
