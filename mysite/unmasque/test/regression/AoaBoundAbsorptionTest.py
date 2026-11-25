from datetime import date

from ...src.core.aoa import InequalityPredicate
from ...src.pipeline.ExtractionPipeLine import ExtractionPipeLine


class _Stub:
    pass


def _bare_aoa():
    """Create an InequalityPredicate without running its DB-backed constructor."""
    return object.__new__(InequalityPredicate)


def _no_op_logger():
    logger = _Stub()
    logger.debug = lambda *args, **kwargs: None
    return logger


def _aoa_from_valid_dmin():
    """AOA seeded with a minimized row that genuinely satisfies A13.

    Orders and lineitem are joined on key 6756; o_orderdate is inside
    ['1993-07-01', '1993-09-30']; l_commitdate <= l_receiptdate.

    The probe callbacks below emulate the DB bound checks used by the real
    filter extractor, so no live database is required.
    """
    dmin = {
        'orders': (['o_orderkey', 'o_orderdate'],
                   (6756, date(1993, 8, 25))),
        'lineitem': (['l_orderkey', 'l_commitdate', 'l_receiptdate'],
                     (6756, date(1993, 10, 27), date(1993, 11, 3))),
    }
    flat_vals = {}
    for attribs, vals in dmin.values():
        flat_vals.update(zip(attribs, vals))

    filter_extractor = _Stub()
    filter_extractor.global_min_instance_dict = dmin
    filter_extractor.global_d_plus_value = dict(flat_vals)
    filter_extractor.global_attrib_max_length = {}

    aoa = _bare_aoa()
    aoa.filter_extractor = filter_extractor
    aoa.global_min_instance_dict = dmin
    aoa.global_d_plus_value = dict(flat_vals)
    aoa.constants_dict = {'date': (date(1, 1, 1), date(9999, 12, 31), 1)}
    aoa.algebraic_eq_predicates = []
    aoa.arithmetic_eq_predicates = []
    aoa._InequalityPredicate__absorbed_LBs = {}
    aoa._InequalityPredicate__absorbed_UBs = {}
    aoa.logger = _no_op_logger()

    def bound_check(tab_attrib, datatype, query):
        if tab_attrib == ('lineitem', 'l_receiptdate'):
            # The only real lower bound is driven by l_commitdate.
            current_commitdate = aoa.global_d_plus_value['l_commitdate']
            return [('lineitem', 'l_receiptdate', '>=',
                     current_commitdate, date(9999, 12, 31))]
        if tab_attrib == ('orders', 'o_orderdate'):
            return [('orders', 'o_orderdate', 'range',
                     date(1993, 7, 1), date(1993, 9, 30))]
        if tab_attrib == ('lineitem', 'l_commitdate'):
            return [('lineitem', 'l_commitdate', '<=',
                     date(1, 1, 1), date(1993, 11, 3))]
        return []

    def mutate(tab_attrib, datatype, val, query, with_UB):
        old_val = aoa.global_d_plus_value[tab_attrib[1]]
        aoa.global_d_plus_value[tab_attrib[1]] = val
        return val, old_val

    def mutate_to_lb(tab_attrib, datatype, query):
        result = bound_check(tab_attrib, datatype, query)
        if result:
            aoa.global_d_plus_value[tab_attrib[1]] = result[0][3]

    aoa._InequalityPredicate__do_bound_check_again = bound_check
    aoa._InequalityPredicate__mutate_attrib_with_Bound_val = mutate
    aoa._InequalityPredicate__mutate_col_to_lb_and_update_setE = mutate_to_lb
    return aoa


def _aoa_with_dormant_bound_probe(b_dot, possible_bound):
    aoa = _bare_aoa()
    aoa.algebraic_eq_predicates = []
    aoa.constants_dict = {'date': (date(1, 1, 1), date(9999, 12, 31), 1)}
    aoa._InequalityPredicate__absorbed_LBs = {}
    aoa._InequalityPredicate__absorbed_UBs = {}
    aoa._InequalityPredicate__reset_dmin_state_for_probe = lambda: None
    aoa._InequalityPredicate__mutate_with_boundary_value = \
        lambda edge_set, datatype, query, tab_attrib, is_UB: b_dot
    aoa._InequalityPredicate__what_is_possible_bound_val = \
        lambda edge_set, edges, tab_attrib, datatype, is_UB: possible_bound
    return aoa


def test_absorbed_dmin_bound_is_not_rediscovered_as_dormant():
    aoa = _aoa_with_dormant_bound_probe(date(1993, 9, 27), date(1, 1, 1))
    col = ('lineitem', 'l_receiptdate')
    aoa._InequalityPredicate__absorbed_LBs = {col: [date(1993, 9, 27)]}

    edge_set = []
    aoa._InequalityPredicate__extract_dormant_concrete_bound(
        edge_set, [], col, 'date', 'SELECT 1', False)

    assert edge_set == []


def test_genuine_bound_differs_from_absorbed_dmin_bound():
    aoa = _aoa_with_dormant_bound_probe(date(1994, 1, 1), date(1, 1, 1))
    col = ('lineitem', 'l_receiptdate')
    aoa._InequalityPredicate__absorbed_LBs = {col: [date(1994, 5, 10)]}

    edge_set = []
    aoa._InequalityPredicate__extract_dormant_concrete_bound(
        edge_set, [], col, 'date', 'SELECT 1', False)

    assert edge_set == [(date(1994, 1, 1), col)]




def _aoa_for_chain_probe(vals, satisfiable):
    aoa = _bare_aoa()
    aoa.constants_dict = {'date': (date(1, 1, 1), date(9999, 12, 31), 1)}
    aoa.algebraic_eq_predicates = []
    aoa._InequalityPredicate__absorbed_LBs = {}
    aoa._InequalityPredicate__absorbed_UBs = {}
    aoa.logger = _no_op_logger()
    original = dict(vals)
    aoa.global_d_plus_value = dict(vals)
    aoa.filter_extractor = _Stub()
    aoa.filter_extractor.global_min_instance_dict = {}
    aoa.filter_extractor.global_d_plus_value = aoa.global_d_plus_value

    def reset():
        aoa.global_d_plus_value.clear()
        aoa.global_d_plus_value.update(original)

    aoa._InequalityPredicate__reset_dmin_state_for_probe = reset
    aoa.get_dmin_val = lambda attrib, tab: aoa.global_d_plus_value[attrib]
    aoa.get_datatype = lambda col: 'date'
    aoa.mutate_dmin_with_val = \
        lambda datatype, col, val: aoa.global_d_plus_value.__setitem__(col[1], val)

    app = _Stub()
    app.doJob = lambda query: True
    app.isQ_result_empty = lambda result: not satisfiable(aoa.global_d_plus_value)
    aoa.app = app
    return aoa


def test_chain_lower_probe_moves_all_predecessors():
    a = ('lineitem', 'l_shipdate')
    b = ('lineitem', 'l_commitdate')
    c = ('lineitem', 'l_receiptdate')
    vals = {
        'l_shipdate': date(1994, 5, 10),
        'l_commitdate': date(1994, 5, 15),
        'l_receiptdate': date(1994, 5, 20),
    }
    aoa = _aoa_for_chain_probe(
        vals, lambda v: all(v[k] >= date(1994, 1, 1) for k in vals))
    edge_set = [(a, b), (b, c), (date(1994, 4, 19), b), (date(1994, 5, 10), c)]

    aoa._InequalityPredicate__rediscover_chain_lower_bounds(
        edge_set, [], 'date', 'SELECT 1')

    assert (date(1994, 1, 1), c) in edge_set
    assert (date(1994, 5, 10), c) not in edge_set
    assert (date(1994, 4, 19), b) in edge_set


def test_chain_upper_probe_moves_all_successors():
    a = ('lineitem', 'l_shipdate')
    b = ('lineitem', 'l_commitdate')
    vals = {
        'l_shipdate': date(1994, 5, 10),
        'l_commitdate': date(1994, 5, 15),
    }
    aoa = _aoa_for_chain_probe(
        vals,
        lambda v: v['l_shipdate'] <= date(1994, 6, 1)
        and v['l_shipdate'] <= v['l_commitdate'])
    edge_set = [(a, b), (a, date(1994, 5, 15))]

    aoa._InequalityPredicate__rediscover_chain_upper_bounds(
        edge_set, [], 'date', 'SELECT 1')

    assert (a, date(1994, 6, 1)) in edge_set
    assert (a, date(1994, 5, 15)) not in edge_set


def test_chain_upper_probe_does_not_add_implied_sink_bound():
    a = ('lineitem', 'l_shipdate')
    b = ('lineitem', 'l_commitdate')
    c = ('lineitem', 'l_receiptdate')
    vals = {
        'l_shipdate': date(1994, 3, 1),
        'l_commitdate': date(1994, 3, 18),
        'l_receiptdate': date(1994, 5, 1),
    }
    aoa = _aoa_for_chain_probe(
        vals, lambda v: all(v[k] <= date(1995, 1, 1) for k in vals))
    edge_set = [(a, b), (b, c), (c, date(1995, 1, 1))]

    aoa._InequalityPredicate__rediscover_chain_upper_bounds(
        edge_set, [], 'date', 'SELECT 1')

    assert (a, date(1995, 1, 1)) not in edge_set


def _aoa_for_rejected_edge(sink_lb, source_ub):
    aoa = _bare_aoa()
    aoa.algebraic_eq_predicates = []
    aoa.constants_dict = {'date': (date(1, 1, 1), date(9999, 12, 31), 1)}
    aoa.logger = _no_op_logger()
    sink = ('lineitem', 'l_receiptdate')
    source = ('orders', 'o_orderdate')
    aoa._InequalityPredicate__absorbed_LBs = {sink: [sink_lb]}
    aoa._InequalityPredicate__absorbed_UBs = {source: [source_ub]}

    def probe(tab_attrib, datatype, query, is_UB):
        if tab_attrib == sink and not is_UB:
            return sink_lb
        return source_ub

    def mutate(tab_attrib, datatype, val, query, with_UB):
        return val, val

    aoa._InequalityPredicate__probe_bound = probe
    aoa._InequalityPredicate__mutate_attrib_with_Bound_val = mutate
    return aoa, source, sink


def test_rejected_LB_edge_keeps_earlier_absorption():
    lb = date(1993, 9, 22)
    ub = date(1993, 9, 30)
    aoa, source, sink = _aoa_for_rejected_edge(lb, ub)
    edge = (source, sink)

    confirmed = aoa._InequalityPredicate__absorb_variable_LBs(
        [edge], [], 'date', source, sink, 'SELECT 1')

    assert confirmed is False
    assert aoa.absorbed_LBs[sink] == [lb]
    assert aoa.absorbed_UBs[source] == [ub]


def test_rejected_UB_edge_keeps_earlier_absorption():
    lb = date(1993, 9, 22)
    ub = date(1993, 9, 30)
    aoa, source, sink = _aoa_for_rejected_edge(lb, ub)
    edge = (source, sink)

    aoa._InequalityPredicate__absorb_variable_UBs(
        [edge], [], 'date', source, sink, 'SELECT 1', False)

    assert aoa.absorbed_LBs[sink] == [lb]
    assert aoa.absorbed_UBs[source] == [ub]


def test_strict_edge_endpoints_are_selected_for_rediscovery():
    aoa = _bare_aoa()
    aoa.algebraic_eq_predicates = []
    aoa._InequalityPredicate__absorbed_LBs = {
        ('orders', 'o_totalprice'): [60000.0]
    }
    aoa._InequalityPredicate__absorbed_UBs = {
        ('lineitem', 'l_extendedprice'): [70000.0]
    }
    strict_edges = [(('lineitem', 'l_extendedprice'), ('orders', 'o_totalprice'))]

    sink_lb = aoa._InequalityPredicate__is_rediscoverable_absorbed_bound(
        ('orders', 'o_totalprice'), strict_edges, is_UB=False)
    source_ub = aoa._InequalityPredicate__is_rediscoverable_absorbed_bound(
        ('lineitem', 'l_extendedprice'), strict_edges, is_UB=True)
    unrelated = aoa._InequalityPredicate__is_rediscoverable_absorbed_bound(
        ('lineitem', 'l_commitdate'), strict_edges, is_UB=True)

    assert sink_lb is True
    assert source_ub is True
    assert unrelated is False


def test_absorbed_bound_suppression_is_direction_specific():
    col = ('lineitem', 'l_extendedprice')
    strict_edges = [(col, ('orders', 'o_totalprice'))]

    aoa = _aoa_with_dormant_bound_probe(70000.0, 60000.0)
    aoa._InequalityPredicate__absorbed_LBs = {col: [70000.0]}

    # An absorbed LB must not suppress UB rediscovery of a strict-edge source.
    edge_set = []
    aoa._InequalityPredicate__extract_dormant_concrete_bound(
        edge_set, strict_edges, col, 'date', 'SELECT 1', True)
    assert edge_set == [(col, 70000.0)]

    # The same absorbed LB is suppressed for LB: this column is not the sink.
    edge_set = []
    aoa._InequalityPredicate__extract_dormant_concrete_bound(
        edge_set, strict_edges, col, 'date', 'SELECT 1', False)
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


def test_false_o_orderdate_edge_is_rejected_from_valid_dmin():
    """The false A13 candidate must not be promoted to '<'."""
    aoa = _aoa_from_valid_dmin()
    src = ('orders', 'o_orderdate')
    sink = ('lineitem', 'l_receiptdate')
    candidate = (src, sink)
    E, L = [candidate], []

    confirmed = aoa._InequalityPredicate__absorb_variable_LBs(
        E, L, 'date', src, sink, 'SELECT 1')

    assert confirmed is False
    assert candidate not in E
    assert candidate not in L


def test_true_l_commitdate_edge_is_confirmed_from_valid_dmin():
    """The real A13 edge must still be accepted and absorb its concrete bounds."""
    aoa = _aoa_from_valid_dmin()
    src = ('lineitem', 'l_commitdate')
    sink = ('lineitem', 'l_receiptdate')
    candidate = (src, sink)
    E = [candidate, (date(1993, 10, 27), sink), (src, date(1993, 11, 3))]
    L = []

    confirmed = aoa._InequalityPredicate__absorb_variable_LBs(
        E, L, 'date', src, sink, 'SELECT 1')
    aoa._InequalityPredicate__absorb_variable_UBs(
        E, L, 'date', src, sink, 'SELECT 1', confirmed)

    assert confirmed is True
    assert candidate in E
    assert candidate not in L
    assert date(1993, 10, 27) in aoa._InequalityPredicate__absorbed_LBs[sink]
    assert date(1993, 10, 27) in aoa._InequalityPredicate__absorbed_UBs[src]
    assert date(1993, 11, 3) in aoa._InequalityPredicate__absorbed_UBs[src]


def test_old_and_new_sink_bounds_both_come_from_bound_check():
    """The old LB must be probed on l_receiptdate, not inferred from E."""
    aoa = _aoa_from_valid_dmin()
    src = ('orders', 'o_orderdate')
    sink = ('lineitem', 'l_receiptdate')
    candidate = (src, sink)
    calls = []
    original = aoa._InequalityPredicate__do_bound_check_again

    def recording(tab_attrib, datatype, query):
        calls.append(tab_attrib)
        return original(tab_attrib, datatype, query)

    aoa._InequalityPredicate__do_bound_check_again = recording

    aoa._InequalityPredicate__absorb_variable_LBs(
        [candidate], [], 'date', src, sink, 'SELECT 1')

    assert calls[0] == sink
    assert calls.count(sink) >= 2


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
