"""CNF/clause-loop extraction scaffolding (spec B6, B8-B11 foundations).

Step 4: algorithmic orchestration for per-clause disjunction extraction with
legacy-compatible output emission hooks. Designed for dependency injection so
core loop/post-processing logic can be unit-tested without a live DB. Not wired
into legacy pipelines by default.
"""

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .extraction import gap, is_necessary, probes, search_atom_numeric
from .model import Atom, Clause, CNF, cnf_to_legacy_or_predicates


@dataclass
class ClauseStatus:
    clause_id: str
    status: str = "OK"  # OK | INCOMPLETE | UNSUPPORTED_SHAPE | AMBIGUOUS_COHOLD | NO_PROGRESS
    reason: Optional[str] = None


@dataclass
class ExtractionResult:
    cnf: CNF
    statuses: List[ClauseStatus] = field(default_factory=list)
    legacy_or_predicates: list = field(default_factory=list)
    complete: bool = True
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> Dict[str, Any]:
        statuses = self.statuses or []
        return {
            "complete": bool(self.complete),
            "clauses": len(getattr(self.cnf, "clauses", []) or []),
            "ok_clauses": sum(1 for s in statuses if getattr(s, "status", None) == "OK"),
            "statuses": [(getattr(s, "clause_id", None), getattr(s, "status", None), getattr(s, "reason", None)) for s in statuses],
            "diagnostics": dict(self.diagnostics or {}),
        }


class CNFDisjunctionExtractor:
    """Dependency-injected clause-loop extractor scaffold.

    Callers provide callbacks for environment-specific operations:
    - extract_atoms(dm_state, excluded_attrs, own_atoms) -> (atoms, row_snapshot)
    - exists_satisfier(clause_index, known_atoms, cnf, iteration_state) -> bool
    - minimize(clause_index, known_atoms, cnf, iteration_state) -> dm_state
    - snapshot_dm(dm_state) -> row_snapshot
    - restore_snap0() -> None
    """

    def __init__(
        self,
        extract_atoms: Callable[[Any, Sequence[Tuple[str, str]], Sequence[Atom]], Tuple[List[Atom], Any]],
        exists_satisfier: Callable[[int, Sequence[Atom], CNF, Any], bool],
        minimize: Callable[[int, Sequence[Atom], CNF, Any], Any],
        snapshot_dm: Optional[Callable[[Any], Any]] = None,
        restore_snap0: Optional[Callable[[], None]] = None,
        max_iters: int = 10000,
        max_retries_zero_atoms: int = 3,
    ):
        self.extract_atoms = extract_atoms
        self.exists_satisfier = exists_satisfier
        self.minimize = minimize
        self.snapshot_dm = snapshot_dm or (lambda s: copy.deepcopy(s))
        self.restore_snap0 = restore_snap0 or (lambda: None)
        # B10 hardening: clamp/validate guardrails to safe positive values.
        try:
            self.max_iters = max(1, int(max_iters))
        except Exception:
            self.max_iters = 10000
        try:
            self.max_retries_zero_atoms = max(1, int(max_retries_zero_atoms))
        except Exception:
            self.max_retries_zero_atoms = 3

    def _mk_clause(self, idx: int, atoms: Sequence[Atom]) -> Clause:
        clause = Clause(id=str(idx), atoms=list(atoms))
        return clause

    def extract(self, dm0_state: Any = None) -> ExtractionResult:
        statuses: List[ClauseStatus] = []
        cnf = CNF()
        diagnostics: Dict[str, Any] = {
            "iterations": 0,
            "satisfier_checks": 0,
            "minimize_calls": 0,
            "extract_calls": 0,
            "retries": 0,
            "clauses_incomplete": 0,
            "clauses_no_progress": 0,
            "clauses_unsupported": 0,
        }

        # Step 1: initial atoms, one per clause (best-effort scaffold)
        try:
            diagnostics["extract_calls"] += 1
            atoms0, row0 = self.extract_atoms(dm0_state, excluded_attrs=[], own_atoms=[])
        except Exception as e:
            self.restore_snap0()
            diagnostics["error"] = str(e)
            return ExtractionResult(cnf=cnf, statuses=[ClauseStatus("init", "INCOMPLETE", str(e))], complete=False, diagnostics=diagnostics)
        self.restore_snap0()

        if not atoms0:
            statuses.append(ClauseStatus("init", "AMBIGUOUS_COHOLD", "No initial atoms extracted"))
            diagnostics["clauses_incomplete"] += 1
            return ExtractionResult(cnf=cnf, statuses=statuses, complete=False, diagnostics=diagnostics)

        for i, atom in enumerate(atoms0):
            atom = copy.deepcopy(atom)
            if atom.id is None:
                atom.id = f"a{i}_0"
            clause = self._mk_clause(i, [atom])
            cnf.clauses.append(clause)
            cnf.row_of[atom.id] = copy.deepcopy(row0)
            statuses.append(ClauseStatus(str(i), "OK"))

        # Step 2: per-clause loop
        for i, clause in enumerate(cnf.clauses):
            st = statuses[i]
            if st.status != "OK":
                continue
            known_i = list(clause.atoms)
            prev_progress_key = None
            iters = 0
            while True:
                iters += 1
                diagnostics["iterations"] += 1
                if iters > self.max_iters:
                    st.status = "NO_PROGRESS"
                    st.reason = f"MAX_ITERS({self.max_iters}) exceeded"
                    diagnostics["clauses_no_progress"] += 1
                    break
                diagnostics["satisfier_checks"] += 1
                if not self.exists_satisfier(i, known_i, cnf, {"iter": iters}):
                    break
                diagnostics["minimize_calls"] += 1
                dm = self.minimize(i, known_i, cnf, {"iter": iters})
                excluded = []
                for k, other in enumerate(cnf.clauses):
                    if k == i:
                        continue
                    excluded.extend(other.attrs())
                # de-dup attrs
                excluded = list(dict.fromkeys(excluded))

                new_atoms = []
                row = None
                # retry on empty result (B6)
                for retry in range(max(1, self.max_retries_zero_atoms)):
                    if retry > 0:
                        diagnostics["retries"] += 1
                    diagnostics["extract_calls"] += 1
                    new_atoms, row = self.extract_atoms(dm, excluded_attrs=excluded, own_atoms=known_i)
                    if len(new_atoms) != 0:
                        break
                    # caller/minimizer may vary dm between retries in real integration

                self.restore_snap0()

                if len(new_atoms) == 1:
                    p = copy.deepcopy(new_atoms[0])
                    if p.id is None:
                        p.id = f"a{i}_{len(clause.atoms)}"
                    # basic duplicate/overlap guard (scaffold for I3)
                    if self._atom_implied_or_duplicate(p, known_i):
                        st.status = "NO_PROGRESS"
                        st.reason = "Extracted atom implied/duplicate; cannot make progress"
                        diagnostics["clauses_no_progress"] += 1
                        break
                    clause.atoms.append(p)
                    known_i.append(p)
                    cnf.row_of[p.id] = copy.deepcopy(row)
                    # progress key scaffold
                    progress_key = (len(known_i), tuple(sorted((a.table, a.col) for a in known_i)))
                    if progress_key == prev_progress_key:
                        st.status = "NO_PROGRESS"
                        st.reason = "No progress in clause state"
                        diagnostics["clauses_no_progress"] += 1
                        break
                    prev_progress_key = progress_key
                    continue
                elif len(new_atoms) == 0:
                    st.status = "INCOMPLETE"
                    st.reason = "AMBIGUOUS_COHOLD"
                    diagnostics["clauses_incomplete"] += 1
                    break
                else:
                    st.status = "UNSUPPORTED_SHAPE"
                    st.reason = "Multiple jointly necessary atoms (conjunctive disjunct or A2 violation)"
                    diagnostics["clauses_unsupported"] += 1
                    break

        # Step 3: interval split scaffold (B8) - placeholder hook
        self._split_merged_clauses(cnf)

        # Step 5: canonicalize and legacy emission
        self._canonicalize(cnf)
        legacy = cnf_to_legacy_or_predicates(cnf)
        complete = all(s.status == "OK" for s in statuses) and len(statuses) == len(cnf.clauses)
        diagnostics["complete"] = complete
        return ExtractionResult(cnf=cnf, statuses=statuses, legacy_or_predicates=legacy, complete=complete, diagnostics=diagnostics)

    @staticmethod
    def _atom_implied_or_duplicate(atom: Atom, known_atoms: Sequence[Atom]) -> bool:
        for k in known_atoms:
            if (k.table, k.col, k.kind) != (atom.table, atom.col, atom.kind):
                continue
            if atom.kind == "text" and k.text == atom.text:
                return True
            if atom.kind != "text":
                # exact interval-set equality treated as duplicate; containment checks can be added later
                if list(k.intervals or []) == list(atom.intervals or []):
                    return True
        return False

    def _split_merged_clauses(self, cnf: CNF):
        """B8 scaffold: interval split of merged cross-clause bounds.

        Full implementation requires SAT checks against row_of states and DB; this
        scaffold preserves structure and is extended during integration.
        """
        return None

    @staticmethod
    def _canonicalize(cnf: CNF):
        for clause in cnf.clauses:
            # deterministic order of atoms
            clause.atoms.sort(key=lambda a: (a.table, a.col, str(getattr(a, 'intervals', None)), str(getattr(a, 'text', None))))
            # merge adjacent/overlapping numeric intervals per same-column atom represented separately not expected here,
            # but normalize within each atom
            for atom in clause.atoms:
                if atom.kind != "text" and atom.intervals:
                    atom.intervals = sorted(atom.intervals, key=lambda x: x[0])
                    merged = []
                    for lo, hi in atom.intervals:
                        if not merged or lo > merged[-1][1]:
                            merged.append([lo, hi])
                        elif hi > merged[-1][1]:
                            merged[-1][1] = hi
                    atom.intervals = [(lo, hi) for lo, hi in merged]
        cnf.clauses.sort(key=lambda c: (c.atoms[0].table, c.atoms[0].col) if c.atoms else ("", ""))

    @staticmethod
    def to_legacy_or_predicates(cnf: CNF):
        return cnf_to_legacy_or_predicates(cnf)
