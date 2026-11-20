import copy
import unittest

from types import SimpleNamespace

from mysite.unmasque.src.core.disjunction import (
    Atom,
    Clause,
    CNF,
    CNFDisjunctionExtractor,
    DbRestorePoint,
    PatternKillScaffold,
    StateSnapshot,
    atom_for_attr,
    atom_from_legacy_pred,
    atoms_from_or_slot,
    cnf_attrs,
    cnf_to_legacy_or_predicates,
    deep_snapshot,
    drop_not_null_sql,
    gap,
    has_cnf_routes,
    is_attr_free,
    is_necessary,
    is_not_true,
    is_true,
    iter_routes,
    keep_predicate_sql,
    legacy_or_predicates_to_cnf,
    pinned_attrs,
    probes,
    representative_value,
    remove_predicate_sql,
    restore_snapshot,
    route_pin_values,
    route_row_snapshots,
    sat_result,
    search_atom_numeric,
    select_route,
    try_null_scaffold,
)
from mysite.unmasque.src.core.dataclass.genPipeline_context import GenPipelineContext
from mysite.unmasque.src.pipeline.fragments.DisjunctionPipeLine import DisjunctionPipeLine
from mysite.unmasque.src.util.configParser import Config


class _Queries:
    def drop_table_cascade(self, t):
        return f"DROP TABLE IF EXISTS {t} CASCADE"

    def drop_table(self, t):
        return f"DROP TABLE IF EXISTS {t}"

    def create_table_as_select_star_from(self, dst, src):
        return f"CREATE TABLE {dst} AS SELECT * FROM {src}"


class _Cfg:
    schema = "unmasque"


class _Conn:
    def __init__(self):
        self.config = _Cfg()
        self.queries = _Queries()
        self.executed = []

    def execute_sql(self, sqls, logger=None):
        self.executed.append(list(sqls))
        return True


class DisjunctionScaffoldingStep1Test(unittest.TestCase):
    def test_atom_clause_cnf_basics(self):
        a = Atom(table="t", col="c", kind="num", intervals=[(1, 5)])
        self.assertEqual(a.attrs(), [("t", "c")])
        self.assertIn("c >=", a.pred_sql(lambda v: v))
        self.assertEqual(a.to_legacy_pred(), ("t", "c", "range", 1, 5))

        eq = Atom(table="t", col="c", kind="num", intervals=[(7, 7)])
        self.assertEqual(eq.to_legacy_pred(), ("t", "c", "equal", 7, 7))

        txt = Atom(table="t", col="name", kind="text", text=("like", "%x%"))
        self.assertEqual(txt.to_legacy_pred(), ("t", "name", "LIKE", "%x%", "%x%"))

        clause = Clause(atoms=[a, eq], id="c0")
        self.assertEqual(clause.attrs(), [("t", "c")])
        self.assertIn("OR", clause.pred_sql(lambda v: v))

        cnf = CNF(clauses=[clause])
        self.assertEqual(len(list(cnf.all_atoms())), 2)

    def test_atom_from_legacy_pred_and_slots(self):
        self.assertIsNone(atom_from_legacy_pred(tuple()))
        self.assertIsNone(atom_from_legacy_pred(None))

        r = atom_from_legacy_pred(("t", "c", "range", 2, 9))
        self.assertEqual(r.intervals, [(2, 9)])

        e = atom_from_legacy_pred(("t", "c", "equal", 3, 3))
        self.assertEqual(e.intervals, [(3, 3)])

        e2 = atom_from_legacy_pred(("t", "c", "=", 4, 4))
        self.assertEqual(e2.intervals, [(4, 4)])

        l = atom_from_legacy_pred(("t", "c", "LIKE", "A%", "A%"))
        self.assertEqual(l.kind, "text")
        self.assertEqual(l.text, ("like", "A%"))

        in_atom = atom_from_legacy_pred(("t", "c", "IN", [1, (2, 4), 6], [1, (2, 4), 6]))
        self.assertIn((2, 4), in_atom.intervals)
        self.assertIn((1, 1), in_atom.intervals)
        self.assertIn((6, 6), in_atom.intervals)

        slot_atoms = atoms_from_or_slot([("t", "c", "equal", 1, 1), tuple(), ("t", "c", "equal", 2, 2)])
        self.assertEqual(len(slot_atoms), 2)

    def test_cnf_legacy_converters(self):
        cnf = legacy_or_predicates_to_cnf([
            (("t", "c", "equal", 1, 1), ("t", "c", "equal", 2, 2)),
            (("t", "d", "range", 5, 10),),
        ])
        self.assertEqual(len(cnf.clauses), 2)
        self.assertEqual(len(cnf.clauses[0].atoms), 2)

        slots = cnf_to_legacy_or_predicates(cnf)
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0][0][0:3], ("t", "c", "equal"))
        self.assertEqual(slots[1][0][0:3], ("t", "d", "range"))

    def test_sat_selection_primitives(self):
        self.assertEqual(is_true("x = 1"), "(x = 1) IS TRUE")
        self.assertEqual(is_not_true("x = 1"), "(x = 1) IS NOT TRUE")
        self.assertEqual(keep_predicate_sql("y > 2"), "(y > 2) IS TRUE")
        self.assertEqual(remove_predicate_sql("y > 2"), "(y > 2) IS NOT TRUE")

        self.assertTrue(sat_result([("h",), (1,)], mode="legacy_nonempty"))
        self.assertFalse(sat_result([("h",)], mode="legacy_nonempty"))

        r_void = [("h",), (0,)]
        self.assertFalse(sat_result([("h",), (0,)], mode="non_prism_void", r_void=r_void))
        self.assertTrue(sat_result([("h",), (1,)], mode="non_prism_void", r_void=r_void))

        self.assertFalse(sat_result([("h",), (None,)], mode="fit"))
        self.assertFalse(sat_result([("h",), (1, None)], mode="fit"))
        self.assertTrue(sat_result([("h",), (1, 2)], mode="fit"))

    def test_config_disjunction_mode_default(self):
        cfg = Config()
        self.assertEqual(getattr(cfg, "disjunction_mode", None), "legacy")


class DisjunctionScaffoldingStep2Test(unittest.TestCase):
    def test_deep_and_state_snapshot_isolation(self):
        state = {"t": [(1, "a")], "n": 2}
        snap = deep_snapshot(state)
        state["t"][0] = (9, "z")
        state["n"] = 99
        self.assertEqual(snap, {"t": [(1, "a")], "n": 2})

        restored = restore_snapshot(snap)
        restored["t"][0] = (7, "x")
        self.assertEqual(snap["t"][0], (1, "a"))

        ss = StateSnapshot.capture(
            global_min_instance_dict={"lineitem": [(1,)]},
            global_d_plus_value={"x": 1},
            filter_attrib_dict={"a": (1, 2)},
            extra={"k": "v"},
        )
        out = ss.restore()
        out["global_min_instance_dict"]["lineitem"][0] = (2,)
        out["global_d_plus_value"]["x"] = 9
        out["extra"]["k"] = "changed"
        self.assertEqual(ss.global_min_instance_dict["lineitem"][0], (1,))
        self.assertEqual(ss.global_d_plus_value["x"], 1)
        self.assertEqual(ss.extras["extra"]["k"], "v")

    def test_drop_not_null_sql_helper(self):
        self.assertEqual(
            drop_not_null_sql("unmasque.t", "c"),
            "ALTER TABLE unmasque.t ALTER COLUMN c DROP NOT NULL;",
        )

    def test_db_restore_point_sql_sequence(self):
        conn = _Conn()
        rp = DbRestorePoint(conn, ["t1", "unmasque.t2"], tag="abc", logger=None)
        self.assertTrue(rp._backup_name("t1").startswith("_cnf_snap_"))
        rp.create()
        self.assertEqual(len(conn.executed), 2)
        self.assertIn("DROP TABLE IF EXISTS unmasque._cnf_snap_t1_abc CASCADE", conn.executed[0][0])
        self.assertIn("CREATE TABLE unmasque._cnf_snap_t1_abc AS SELECT * FROM unmasque.t1", conn.executed[0][1])
        self.assertIn("CREATE TABLE unmasque._cnf_snap_unmasque_t2_abc AS SELECT * FROM unmasque.t2", conn.executed[1][1])
        self.assertEqual(len(rp.created), 2)

        conn.executed.clear()
        rp.restore()
        self.assertEqual(len(conn.executed), 2)
        # restore should apply in reverse order of creation
        self.assertIn("AS SELECT * FROM unmasque._cnf_snap_unmasque_t2_abc", conn.executed[0][1])
        self.assertIn("AS SELECT * FROM unmasque._cnf_snap_t1_abc", conn.executed[1][1])

        conn.executed.clear()
        rp.drop()
        self.assertEqual(len(conn.executed), 2)
        self.assertEqual(rp.created, [])


class DisjunctionScaffoldingStep3Test(unittest.TestCase):
    def test_gap_and_probes(self):
        self.assertEqual(gap("x", 5, [], 0, 30), (0, 30))
        own = [
            Atom(table="t", col="x", intervals=[(10, 12)]),
            Atom(table="t", col="x", intervals=[(0, 2)]),
        ]
        self.assertEqual(gap("x", 5, own, 0, 30), (2, 10))
        self.assertEqual(gap("x", 11, own, 0, 30), (11, 11))

        ps = probes("x", 0, 10, step=1, k_interior=4, distinct_values=[3, 3, 7, 15], max_distinct=32)
        self.assertIn(0, ps)
        self.assertIn(10, ps)
        self.assertTrue(all(0 <= p <= 10 for p in ps))
        self.assertEqual(len(ps), len(set(ps)))

    def test_necessity_and_search_refine(self):
        nr = is_necessary("x", 0, 10, lambda x, v: False, [1, 2])
        self.assertTrue(nr.necessary)
        self.assertIn(nr.witness, (1, 2))
        nr = is_necessary("x", 0, 10, lambda x, v: True, [1, 2])
        self.assertFalse(nr.necessary)

        atom = search_atom_numeric(
            "t", "x", 0, 30, 5, lambda x, v: 3 <= v <= 9, step=1,
            probe_values=probes("x", 0, 30, 1, 8, list(range(0, 31))),
        )
        self.assertEqual(atom.intervals, [(3, 9)])

        atom = search_atom_numeric(
            "t", "x", 0, 30, 5, lambda x, v: v == 5, step=1,
            probe_values=probes("x", 0, 30, 1, 8, list(range(0, 31))),
        )
        self.assertEqual(atom.intervals, [(5, 5)])

        atom = search_atom_numeric(
            "t", "x", 0, 30, 2, lambda x, v: v <= 3 or v >= 20, step=1,
            probe_values=probes("x", 0, 30, 1, 16, list(range(0, 31))),
        )
        self.assertEqual(atom.intervals, [(0, 3), (20, 30)])

    def test_try_null_and_pattern_kill_scaffolds(self):
        state = {"nulled": False, "val": 5}
        res = try_null_scaffold(
            "x",
            lambda x: state.update(nulled=True),
            lambda: False,
            lambda x: state.update(nulled=False, val=5),
        )
        self.assertFalse(res.sat)
        self.assertFalse(state["nulled"])

        pk = PatternKillScaffold(max_columns=6)
        self.assertFalse(pk.should_skip(["a", "b"]))
        self.assertTrue(pk.should_skip(["a", "b", "c", "d", "e", "f", "g"]))
        pats = pk.patterns(["a", "b"], choices=("o", "m"))
        self.assertEqual(len(pats), 4)
        self.assertEqual(pats[0], {"a": "o", "b": "o"})


class DisjunctionScaffoldingStep4Test(unittest.TestCase):
    def test_clause_loop_extension_and_legacy_emission(self):
        sat_state = {"c0": 0}

        def extract_atoms(dm, excluded_attrs, own_atoms):
            if excluded_attrs == [] and own_atoms == [] and dm == "dm0":
                return [Atom("t", "x", intervals=[(1, 1)]), Atom("t", "y", intervals=[(5, 5)])], {"r": 0}
            if dm == "dm_c0_1":
                return [Atom("t", "x", intervals=[(2, 2)])], {"r": 1}
            return [], {}

        def exists_satisfier(i, known, cnf, itst):
            if i == 0:
                sat_state["c0"] += 1
                return sat_state["c0"] == 1
            return False

        def minimize(i, known, cnf, itst):
            return "dm_c0_1" if i == 0 else "dm_other"

        ex = CNFDisjunctionExtractor(extract_atoms, exists_satisfier, minimize)
        res = ex.extract("dm0")
        self.assertEqual(len(res.cnf.clauses), 2)
        self.assertEqual(len(res.cnf.clauses[0].atoms), 2)
        self.assertEqual([a.intervals for a in res.cnf.clauses[0].atoms], [[(1, 1)], [(2, 2)]])
        self.assertTrue(all(s.status == "OK" for s in res.statuses))
        self.assertEqual(len(res.legacy_or_predicates), 2)
        self.assertEqual(res.legacy_or_predicates[0][0][0:3], ("t", "x", "equal"))
        self.assertEqual(res.legacy_or_predicates[0][1][3], 2)

    def test_unsupported_shape_and_incomplete_statuses(self):
        def extract_atoms_multi(dm, excluded_attrs, own_atoms):
            if excluded_attrs == [] and own_atoms == []:
                return [Atom("t", "x", intervals=[(1, 1)])], {}
            return [Atom("t", "x", intervals=[(2, 2)]), Atom("t", "z", intervals=[(3, 3)])], {}

        ex = CNFDisjunctionExtractor(
            extract_atoms_multi,
            lambda i, known, cnf, it: i == 0 and len(known) == 1,
            lambda i, k, c, it: "dm",
        )
        res = ex.extract("dm0")
        self.assertEqual(res.statuses[0].status, "UNSUPPORTED_SHAPE")

        def extract_atoms_zero(dm, excluded_attrs, own_atoms):
            if excluded_attrs == [] and own_atoms == []:
                return [Atom("t", "x", intervals=[(1, 1)])], {}
            return [], {}

        ex2 = CNFDisjunctionExtractor(
            extract_atoms_zero,
            lambda i, known, cnf, it: i == 0 and len(known) == 1,
            lambda i, k, c, it: "dm",
            max_retries_zero_atoms=2,
        )
        res2 = ex2.extract("dm0")
        self.assertEqual(res2.statuses[0].status, "INCOMPLETE")


class _NullLogger:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def error(self, *a, **k): pass


class _FilterExtractorStub:
    def __init__(self):
        self.global_all_attribs = {}
        self.global_attrib_types = []
    def get_datatype(self, tab_attrib):
        return "numeric"
    def get_dmin_val(self, attrib, tab):
        return 0


class _AoaStub:
    def __init__(self):
        self.arithmetic_filters = []
        self.algebraic_eq_predicates = []
        self.aoa_predicates = []
        self.aoa_less_thans = []
    def do_permanent_mutation(self):
        return {}
    def restore_d_min_from_dict(self):
        return None


class _StubDisjunctionPipeline(DisjunctionPipeLine):
    def __init__(self, returned_predicates, detect_or=True, mode="legacy"):
        self.OR_CUTOFF = 1000
        self.logger = _NullLogger()
        self.connectionHelper = SimpleNamespace(config=SimpleNamespace(detect_or=detect_or, disjunction_mode=mode))
        self.filter_extractor = SimpleNamespace(get_datatype=lambda ta: "numeric")
        self.state = []
        self.all_sizes = {}
        self.returned_predicates = returned_predicates
        self.disjunction_cnf = None
        self.disjunction_statuses = None
    def _mutation_pipeline(self, core_relations, query, time_profile, restore_details=None, expect_populated=True):
        return True, time_profile
    def _DisjunctionPipeLine__get_predicates_in_action(self):
        return self.returned_predicates
    def process(self, query): pass
    def doJob(self, query, qe=None): pass
    def verify_correctness(self, query, result): pass
    def extract(self, query): pass


class DisjunctionScaffoldingStep5Test(unittest.TestCase):
    def test_genpipeline_context_derives_or_predicates_from_cnf(self):
        cnf = CNF(clauses=[Clause(atoms=[Atom("t", "x", intervals=[(1, 1)]), Atom("t", "x", intervals=[(2, 2)])])])
        ctx = GenPipelineContext(["t"], _AoaStub(), _FilterExtractorStub(), {}, None, cnf=cnf)
        derived = ctx._GenPipelineContext__or_predicates
        self.assertEqual(len(derived), 1)
        self.assertEqual(derived[0][0][0:3], ("t", "x", "equal"))
        self.assertEqual(ctx.cnf, cnf)

    def test_cnf_mode_hook_falls_back_to_legacy_extraction(self):
        initial = ("t", "x", "range", 1, 5)
        # returned predicate differs in a non-overlapping way? legacy test expects no new disjunct when overlapping
        # simulate no new disjunct found
        p = _StubDisjunctionPipeline([("t", "x", "range", 1, 5)], detect_or=True, mode="cnf")
        check, _ = p._extract_disjunction([initial], ["t"], "q", None)
        self.assertTrue(check)
        self.assertEqual(p.or_predicates, [(initial,)])
        self.assertIsNone(p.disjunction_cnf)


class DisjunctionScaffoldingStep6Test(unittest.TestCase):
    def test_route_helpers_selection_pinning_and_snapshots(self):
        a1 = Atom("t", "x", intervals=[(1, 1)], id="a1")
        a2 = Atom("t", "x", intervals=[(2, 2)], id="a2")
        b1 = Atom("t", "y", kind="text", text=("eq", "hi"), id="b1")
        cnf = CNF(clauses=[Clause(atoms=[a1, a2]), Clause(atoms=[b1])], row_of={"a1": {"v": 1}, "b1": {"v": "hi"}})

        self.assertTrue(has_cnf_routes(cnf))
        r0 = select_route(cnf, 0)
        self.assertEqual(len(r0), 2)
        self.assertEqual(r0[0].id, "a1")
        self.assertEqual(r0[1].id, "b1")
        routes = list(iter_routes(cnf))
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[1][0].id, "a2")

        self.assertEqual(pinned_attrs(r0), [("t", "x"), ("t", "y")])
        self.assertFalse(is_attr_free(("t", "x"), r0))
        self.assertTrue(is_attr_free(("t", "z"), r0))
        self.assertEqual(atom_for_attr(r0, "t", "y").id, "b1")
        self.assertEqual(representative_value(a1), 1)
        self.assertEqual(representative_value(Atom("t", "z", intervals=[(10, 20)])), 11)
        self.assertEqual(representative_value(Atom("t", "s", kind="text", text=("like", "ab%"))), "aba")
        pins = route_pin_values(r0)
        self.assertEqual(pins[("t", "x")], 1)
        self.assertEqual(pins[("t", "y")], "hi")
        snaps = route_row_snapshots(cnf, r0)
        self.assertEqual(snaps, [{"v": 1}, {"v": "hi"}])
        self.assertEqual(cnf_attrs(cnf), [("t", "x"), ("t", "y")])

        self.assertFalse(has_cnf_routes(None))
        self.assertFalse(has_cnf_routes(CNF()))
        self.assertIsNone(select_route(None))
        self.assertEqual(route_pin_values(None), {})

    def test_genpipeline_context_exposes_cnf_route_and_pins(self):
        cnf = CNF(clauses=[Clause(atoms=[Atom("t", "x", intervals=[(5, 5)], id="a1")])], row_of={"a1": {"r": 1}})
        ctx = GenPipelineContext(["t"], _AoaStub(), _FilterExtractorStub(), {}, None, cnf=cnf)
        self.assertIsNotNone(ctx.cnf_route)
        self.assertEqual(ctx.cnf_pin_values.get(("t", "x")), 5)

        ctx2 = GenPipelineContext(["t"], _AoaStub(), _FilterExtractorStub(), {}, None, cnf=None)
        self.assertIsNone(ctx2.cnf_route)
        self.assertEqual(ctx2.cnf_pin_values, {})

    def test_base_generation_pin_helpers_guarded(self):
        # Minimal duck-typed object exercising GenerationPipeLineBase methods.
        from mysite.unmasque.src.core.abstract.GenerationPipeLineBase import GenerationPipeLineBase

        obj = SimpleNamespace()
        obj.cnf_pin_values = {("t", "x"): 7}
        obj.filter_attrib_dict = {}
        obj.get_datatype = lambda key: "int"
        obj.get_s_val_for_textType = lambda a, t: "x"
        obj.logger = _NullLogger()
        self.assertEqual(GenerationPipeLineBase.get_cnf_pinned_or_none(obj, "t", "x"), 7)
        self.assertIsNone(GenerationPipeLineBase.get_cnf_pinned_or_none(obj, "t", "y"))
        self.assertEqual(GenerationPipeLineBase.get_s_val(obj, "x", "t"), 7)

        obj2 = SimpleNamespace()
        obj2.cnf_pin_values = {}
        obj2.filter_attrib_dict = {("t", "n"): (10, 20)}
        obj2.get_datatype = lambda key: "int"
        obj2.get_s_val_for_textType = lambda a, t: "x"
        obj2.logger = _NullLogger()
        self.assertEqual(GenerationPipeLineBase.get_s_val(obj2, "n", "t"), 10)


if __name__ == "__main__":
    unittest.main()
