"""Regressions for equi-join/filter integration around pinned join groups."""
from ...src.core.aoa import InequalityPredicate
from ...src.core.dataclass.genPipeline_context import GenPipelineContext
from ...src.core.equi_join import U2EquiJoin


class _Stub:
    pass


def _no_op_logger():
    logger = _Stub()
    logger.debug = lambda *args, **kwargs: None
    return logger


def _bare_equi_join(filter_attribs):
    equi_join = object.__new__(U2EquiJoin)
    equi_join.logger = _no_op_logger()
    equi_join.algebraic_eq_predicates = []
    equi_join.arithmetic_eq_predicates = []
    equi_join.get_datatype = lambda tab_attrib: 'int'
    equi_join._extract_filter_on_attrib_set = (
        lambda result, query, attrib_list, datatype: result.extend(filter_attribs))
    return equi_join


def test_pinned_join_group_keeps_constant_filter_on_every_member():
    equi_join = _bare_equi_join([('customer', 'c_nationkey', '=', 1, 1)])
    group = [('customer', 'c_nationkey'), ('nation', 'n_nationkey')]

    assert equi_join.handle_unit_eq_group(group, 'SELECT 1') is False

    # No spurious join is emitted for a group pinned by a constant filter, but
    # the filter that pinned it must survive on both join-equivalent columns.
    assert equi_join.algebraic_eq_predicates == []
    assert ('customer', 'c_nationkey', '=', 1, 1) in equi_join.arithmetic_eq_predicates
    assert ('nation', 'n_nationkey', '=', 1, 1) in equi_join.arithmetic_eq_predicates


def test_unpinned_join_group_still_emitted():
    equi_join = _bare_equi_join([('customer', 'c_nationkey', 'range', 1, 25)])
    group = [('customer', 'c_nationkey'), ('nation', 'n_nationkey')]

    assert equi_join.handle_unit_eq_group(group, 'SELECT 1') is True
    assert equi_join.algebraic_eq_predicates == [group]
    assert equi_join.arithmetic_eq_predicates == []


def _bare_context(arithmetic_filters, filter_attrib_dict, eq_groups, aoa_attribs=()):
    ctx = object.__new__(GenPipelineContext)
    ctx.arithmetic_filters = arithmetic_filters
    ctx.filter_attrib_dict = filter_attrib_dict
    ctx._GenPipelineContext__algebraic_eq_predicates = eq_groups
    ctx._GenPipelineContext__aoa_attribs = list(aoa_attribs)
    ctx._cross_column_or_constituent_keys = set()
    ctx._cross_column_or_constituent_preds = set()
    ctx.cross_column_or_predicates = []
    ctx.filter_in_predicates = []
    ctx._GenPipelineContext__or_predicates = []
    ctx.get_datatype = lambda key: 'int'
    return ctx


def test_joined_alias_does_not_become_spurious_standalone_bound():
    ctx = _bare_context(
        arithmetic_filters=[
            ('customer', 'c_custkey', '>=', 5001, 9999999),
            ('customer', 'c_acctbal', '<=', -9999999.99, 6999.99),
        ],
        filter_attrib_dict={
            ('customer', 'c_custkey'): (5001, 9999999),
            ('orders', 'o_custkey'): (5001, 9999999),
            ('customer', 'c_acctbal'): (-9999999.99, 6999.99),
            ('orders', 'o_totalprice'): (353284.26, 9999999.99),
        },
        eq_groups=[[('customer', 'c_custkey'), ('orders', 'o_custkey')]],
        aoa_attribs=[('orders', 'o_totalprice')],
    )

    ctx._GenPipelineContext__update_filter_predicates_from_filter_dict()

    assert ('orders', 'o_custkey', '>=', 5001, 9999999) not in ctx.arithmetic_filters
    assert ('customer', 'c_custkey', '>=', 5001, 9999999) in ctx.arithmetic_filters


def test_distinct_filter_on_joined_alias_is_kept():
    ctx = _bare_context(
        arithmetic_filters=[('customer', 'c_custkey', '>=', 5001, 9999999)],
        filter_attrib_dict={
            ('customer', 'c_custkey'): (5001, 9999999),
            ('orders', 'o_custkey'): (6000, 9999999),
        },
        eq_groups=[[('customer', 'c_custkey'), ('orders', 'o_custkey')]],
    )

    ctx._GenPipelineContext__update_filter_predicates_from_filter_dict()

    assert ('orders', 'o_custkey', '>=', 6000, 9999999) in ctx.arithmetic_filters


def test_incomplete_or_slot_does_not_duplicate_canonical_bound():
    ctx = _bare_context(
        arithmetic_filters=[('customer', 'c_nationkey', 'range', 1, 11)],
        filter_attrib_dict={},
        eq_groups=[],
    )
    ctx._GenPipelineContext__or_predicates = [
        (('customer', 'c_nationkey', 'range', 1, 5), ()),
    ]

    ctx._GenPipelineContext__generate_arithmetic_conjunctive_disjunctions()

    assert ctx.arithmetic_filters == [('customer', 'c_nationkey', 'range', 1, 11)]


def test_single_alternative_or_slot_still_appends_missing_bound():
    ctx = _bare_context(
        arithmetic_filters=[],
        filter_attrib_dict={},
        eq_groups=[],
    )
    ctx._GenPipelineContext__or_predicates = [
        (('customer', 'c_nationkey', 'range', 1, 5),),
    ]

    ctx._GenPipelineContext__generate_arithmetic_conjunctive_disjunctions()

    assert ctx.arithmetic_filters == [('customer', 'c_nationkey', 'range', 1, 5)]


def _bare_aoa(ranges):
    aoa = object.__new__(InequalityPredicate)
    aoa.logger = _no_op_logger()
    aoa.arithmetic_filters = []
    aoa.arithmetic_eq_predicates = []
    aoa.arithmetic_ineq_predicates = list(ranges)
    aoa.aoa_predicates = []
    return aoa


def test_aoa_keeps_broader_range_when_narrower_range_arrives_first():
    aoa = _bare_aoa([
        ('customer', 'c_nationkey', 'range', 1, 5),
        ('customer', 'c_nationkey', 'range', 1, 11),
    ])

    aoa._InequalityPredicate__fill_in_internal_predicates()

    assert aoa.arithmetic_filters == [('customer', 'c_nationkey', 'range', 1, 11)]


def test_aoa_drops_narrower_range_when_broader_range_arrives_first():
    aoa = _bare_aoa([
        ('customer', 'c_nationkey', 'range', 1, 11),
        ('customer', 'c_nationkey', 'range', 1, 5),
    ])

    aoa._InequalityPredicate__fill_in_internal_predicates()

    assert aoa.arithmetic_filters == [('customer', 'c_nationkey', 'range', 1, 11)]
