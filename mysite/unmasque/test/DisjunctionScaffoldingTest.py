import copy
import unittest

from mysite.unmasque.src.core.disjunction import (
    Atom,
    Clause,
    CNF,
    DbRestorePoint,
    StateSnapshot,
    atom_from_legacy_pred,
    atoms_from_or_slot,
    cnf_to_legacy_or_predicates,
    deep_snapshot,
    drop_not_null_sql,
    is_not_true,
    is_true,
    keep_predicate_sql,
    legacy_or_predicates_to_cnf,
    remove_predicate_sql,
    restore_snapshot,
    sat_result,
)
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


if __name__ == "__main__":
    unittest.main()
