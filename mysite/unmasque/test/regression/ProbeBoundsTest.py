"""Regression tests for the shared AOA-aware probe-data generator."""
from datetime import date

from ...src.core.abstract.GenerationPipeLineBase import GenerationPipeLineBase


class _Stub:
    pass


def _no_op_logger():
    logger = _Stub()
    logger.debug = lambda *args, **kwargs: None
    logger.info = lambda *args, **kwargs: None
    return logger


class _NoDbConnection:
    def execute_sql_fetchone_0(self, _sql):
        return None


def _bound_aware_base():
    """Build a GenerationPipeLineBase with no database operations."""
    obj = object.__new__(GenerationPipeLineBase)
    obj.logger = _no_op_logger()
    obj.connectionHelper = _NoDbConnection()
    obj.cnf_pin_values = {}
    obj.get_fully_qualified_table_name = lambda tab: tab
    obj.get_dmin_val = lambda col, tab: {
        ('lineitem', 'l_shipdate'): date(1994, 7, 23),
        ('lineitem', 'l_commitdate'): date(1994, 7, 24),
        ('lineitem', 'l_receiptdate'): date(1994, 7, 29),
        ('lineitem', 'l_extendedprice'): 8203.20,
        ('orders', 'o_totalprice'): 217972.39,
    }[(tab, col)]
    obj.get_datatype = lambda key: 'date' if key[1].endswith('date') else 'numeric'
    obj.filter_attrib_dict = {
        ('lineitem', 'l_receiptdate'): (date(1, 1, 1), date(1995, 1, 1)),
        ('lineitem', 'l_extendedprice'): (-9999999.99, 217972.38),
        ('orders', 'o_totalprice'): (8203.21, 9999999.99),
    }
    ctx = _Stub()
    ctx._absorbed_LBs = {
        ('lineitem', 'l_commitdate'): [date(1994, 7, 23), date(1994, 7, 24)],
        ('lineitem', 'l_receiptdate'): [date(1994, 7, 24), date(1994, 7, 29)],
        ('orders', 'o_totalprice'): [60000.0, 70000.0],
    }
    ctx._absorbed_UBs = {
        ('lineitem', 'l_commitdate'): [date(1994, 7, 24), date(1994, 7, 29)],
        ('lineitem', 'l_extendedprice'): [60000.0, 70000.0],
        ('lineitem', 'l_shipdate'): [date(1994, 7, 23), date(1994, 7, 24)],
    }
    ctx.global_aoa_le_predicates = [
        (('lineitem', 'l_shipdate'), ('lineitem', 'l_commitdate')),
        (('lineitem', 'l_commitdate'), ('lineitem', 'l_receiptdate')),
    ]
    ctx.global_aoa_l_predicates = [
        (('lineitem', 'l_extendedprice'), ('orders', 'o_totalprice')),
    ]
    obj._gen_ctx = ctx
    return obj


def test_absorbed_bounds_are_part_of_effective_bounds():
    base = _bound_aware_base()
    # The strongest absorbed lower bound on o_totalprice is 70000, and the
    # strict edge l_extendedprice < o_totalprice tightens it by one delta.
    assert base.get_effective_bounds('orders', 'o_totalprice', 'numeric')[0] == 70000.01
    # Likewise, the strongest absorbed upper bound on l_extendedprice is 60000.
    assert base.get_effective_bounds('lineitem', 'l_extendedprice', 'numeric')[1] == 59999.99
    assert base.get_effective_bounds('lineitem', 'l_commitdate', 'date') == (
        date(1994, 7, 24), date(1994, 7, 24))


def test_generated_numeric_pair_satisfies_strict_aoa_edge():
    base = _bound_aware_base()
    left = base.get_s_value_within_bounds('lineitem', 'l_extendedprice', 'numeric')
    right = base.get_s_value_within_bounds('orders', 'o_totalprice', 'numeric')
    assert left <= 70000.0
    assert right >= 60000.0
    assert left < right


def test_generated_date_chain_satisfies_all_le_edges():
    base = _bound_aware_base()
    ship = base.get_s_value_within_bounds('lineitem', 'l_shipdate', 'date')
    commit = base.get_s_value_within_bounds('lineitem', 'l_commitdate', 'date')
    receipt = base.get_s_value_within_bounds('lineitem', 'l_receiptdate', 'date')
    assert ship <= commit <= receipt
    assert receipt <= date(1995, 1, 1)


def test_distinct_probe_values_stay_inside_bounds():
    base = _bound_aware_base()
    first = base.get_s_value_within_bounds('lineitem', 'l_extendedprice', 'numeric')
    second = base.get_s_value_plus_delta_within_bounds('lineitem', 'l_extendedprice',
                                                        'numeric', 1, prev=first)
    assert first < second <= 59999.99
