import copy
from abc import abstractmethod, ABC

from ...core.abstract.MinimizerBase import Minimizer
from ...util.constants import UNMASQUE
from ....src.core.aoa import InequalityPredicate
from ....src.core.cs2 import Cs2
from ....src.core.db_restorer import DbRestorer
from ....src.core.equi_join import U2EquiJoin
from ....src.core.filter import Filter
from ....src.core.minimizer_factory import create_minimizer
from ....src.pipeline.abstract.generic_pipeline import GenericPipeLine
from ....src.util.aoa_utils import get_constants_for
from ....src.util.constants import FILTER, INEQUALITY, DONE, RUNNING, START, EQUALITY, DB_MINIMIZATION, \
    SAMPLING, RESTORE_DB, ERROR
from ....src.util.utils import get_format, get_val_plus_delta
from ....src.util.error_handling import UnmasqueError
from ....src.util.error_codes import ERROR_008
from ....src.pipeline.abstract.SchemaSanitizer import SchemaSanitizer


def get_eq_filters(arithmetics):
    return [pred for pred in arithmetics if pred[2] in ['equal', '=']]


def probe_expects_populated(restore_details):
    """Whether an OR-probe database is expected to answer the query.

    An OR probe deliberately falsifies the candidate predicates, so the working
    schema is expected to return no rows. Any non-trivial ``where`` clause marks
    such a falsified probe; all-``true`` clauses mean the database is restored
    normally and a populated result is still expected.
    """
    if not restore_details:
        return True
    return not any(str(where).strip().lower() != 'true' for _, where in restore_details)


class DisjunctionPipeLine(GenericPipeLine, ABC):

    def __init__(self, connectionHelper, name):
        GenericPipeLine.__init__(self, connectionHelper, name)
        self.aoa = None
        self.equi_join = None
        self.filter_extractor = None
        self.db_restorer = None
        self.global_min_instance_dict = None
        self.key_lists = None
        self.OR_CUTOFF = 1000
        # CNF disjunction integration scaffolding (non-legacy modes only).
        self.disjunction_cnf = None
        self.disjunction_statuses = None

    def get_disjunction_diagnostics(self):
        """B12 (guarded): return lightweight CNF/status diagnostics when available."""
        diag = {
            "mode": str(getattr(getattr(self, 'connectionHelper', None), 'config', None) and getattr(self.connectionHelper.config, 'disjunction_mode', 'legacy') or 'legacy'),
            "has_cnf": getattr(self, 'disjunction_cnf', None) is not None,
            "statuses": None,
            "cnf": None,
        }
        statuses = getattr(self, 'disjunction_statuses', None)
        if statuses is not None:
            try:
                diag["statuses"] = [(getattr(s, 'clause_id', None), getattr(s, 'status', None), getattr(s, 'reason', None)) for s in statuses]
            except Exception:
                diag["statuses"] = statuses
        cnf = getattr(self, 'disjunction_cnf', None)
        if cnf is not None:
            try:
                from ...core.disjunction.routes import verify_cnf_structure
                diag["cnf"] = verify_cnf_structure(cnf)
            except Exception:
                diag["cnf"] = {"present": True, "error": "verification_failed"}
        return diag

    def _mutation_pipeline(self, core_relations, query, time_profile, restore_details=None,
                           expect_populated=True):
        self.update_state(RESTORE_DB + START)
        self.db_restorer = DbRestorer(self.connectionHelper, core_relations)
        self.db_restorer.set_data_schema()
        self.db_restorer.set_all_sizes(self.all_sizes)
        # for tab in core_relations:
        #    self.db_restorer.last_restored_size[tab] = self.all_sizes[tab]
        self.update_state(RESTORE_DB + RUNNING)
        check = self.db_restorer.doJob(restore_details)
        self.update_state(RESTORE_DB + DONE)
        time_profile.update_for_db_restore(self.db_restorer.local_elapsed_time, self.db_restorer.app_calls)
        if not check or not self.db_restorer.done:
            self.info[RESTORE_DB] = None
            self.logger.info("DB restore failed!")
            return False, time_profile
        self.info[RESTORE_DB] = {'size': self.db_restorer.last_restored_size}

        """
        Correlated Sampling
        """
        self.update_state(SAMPLING + START)
        cs2 = Cs2(self.connectionHelper, self.all_sizes, core_relations, self.key_lists, perc_based_cutoff=True)
        self.update_state(SAMPLING + RUNNING)
        check = cs2.doJob(query)
        self.update_state(SAMPLING + DONE)
        time_profile.update_for_cs2(cs2.local_elapsed_time, cs2.app_calls)
        if not check or not cs2.done:
            self.info[SAMPLING] = None
            self.logger.info("Sampling failed!")
        if not self.connectionHelper.config.use_cs2:
            self.info[SAMPLING] = SAMPLING + "DISABLED"
            self.logger.info("Sampling is disabled!")
        else:
            self.info[SAMPLING] = {'sample': cs2.sample, 'size': cs2.sizes}

        """
            View based Database Minimization
            """
        self.update_state(DB_MINIMIZATION + START)
        vm = create_minimizer(self.connectionHelper, core_relations, self.db_restorer.last_restored_size, cs2.passed,
                              expect_populated=expect_populated)
        self.update_state(DB_MINIMIZATION + RUNNING)
        try:
            check = vm.doJob(query)
            self.update_state(DB_MINIMIZATION + DONE)
            time_profile.update_for_view_minimization(vm.local_elapsed_time, vm.app_calls)
        except UnmasqueError as e:
            e.report_to_logger(self.logger)

        if not check or not vm.done:
            if expect_populated:
                # self.error = "Cannot do database minimization"
                self.logger.error(self.error)
                self.update_state(ERROR)
            else:
                # A falsified OR probe is expected to be empty; no disjunct
                # exists here, so this is not an error.
                self.logger.info("No disjunct exists; skipping database minimization for this OR probe.")
            self.info[DB_MINIMIZATION] = None
            return False, time_profile

        self.db_restorer.update_last_restored_size(vm.all_sizes)
        self.info[DB_MINIMIZATION] = vm.global_min_instance_dict
        self.global_min_instance_dict = copy.deepcopy(vm.global_min_instance_dict)

        '''
        Constant Filter Extraction
        '''
        self.update_state(FILTER + START)
        self.filter_extractor = Filter(self.connectionHelper, core_relations, self.global_min_instance_dict)
        self.update_state(FILTER + RUNNING)
        check = self.filter_extractor.doJob(query)
        self.update_state(FILTER + DONE)
        time_profile.update_for_where_clause(self.filter_extractor.local_elapsed_time,
                                             self.filter_extractor.app_calls)
        if not self.filter_extractor.done:
            self.update_state(ERROR)
            self.info[FILTER] = None
            self.error = check if check else self.error_string
            self.logger.error(self.error)
            return False, time_profile
        if not check:
            self.info[FILTER] = None
            self.logger.info("No filter found")
        self.info[FILTER] = self.filter_extractor.filter_predicates

        '''
        Equality Relations (Equi-join + Constant Equality filters) Extraction
        '''
        self.update_state(EQUALITY + START)
        self.update_state(EQUALITY + RUNNING)
        self.equi_join = U2EquiJoin(self.connectionHelper, core_relations, self.filter_extractor.filter_predicates,
                                    self.filter_extractor, self.global_min_instance_dict)
        check = self.equi_join.doJob(query)
        self.update_state(EQUALITY + DONE)
        time_profile.update_for_where_clause(self.equi_join.local_elapsed_time, self.equi_join.app_calls)
        if not self.equi_join.done:
            self.update_state(ERROR)
            self.info[EQUALITY] = None
            self.error = check if check else self.error_string
            self.logger.error(self.error)
            return False, time_profile
        if not check:
            self.info[EQUALITY] = None
            self.logger.info("No Equality predicate found")
        combined_eq_predicates = self.equi_join.algebraic_eq_predicates + self.equi_join.arithmetic_eq_predicates
        self.info[EQUALITY] = combined_eq_predicates

        '''
        AOA Extraction
        '''
        self.update_state(INEQUALITY + START)
        self.aoa = InequalityPredicate(self.connectionHelper, core_relations, self.equi_join.pending_predicates,
                                       self.equi_join.arithmetic_eq_predicates,
                                       self.equi_join.algebraic_eq_predicates, self.filter_extractor,
                                       self.global_min_instance_dict)
        self.update_state(INEQUALITY + RUNNING)
        check = self.aoa.doJob(query)
        self.update_state(INEQUALITY + DONE)
        time_profile.update_for_where_clause(self.aoa.local_elapsed_time, self.aoa.app_calls)
        self.info[INEQUALITY] = self.aoa.aoa_predicates + self.aoa.aoa_less_thans + self.aoa.arithmetic_ineq_predicates
        if not check:
            self.info[INEQUALITY] = None
            self.logger.info("Cannot find inequality Predicates.")
        if not self.aoa.done:
            self.info[INEQUALITY] = None
            self.error = check if check else self.error_string
            self.logger.error(self.error)
            self.update_state(ERROR)
            return False, time_profile
        return True, time_profile

    def __get_predicates_in_action(self):
        return self.aoa.arithmetic_filters

    @abstractmethod
    def process(self, query: str):
        raise NotImplementedError("Trouble!")

    @abstractmethod
    def doJob(self, query, qe=None):
        raise NotImplementedError("Trouble!")

    @abstractmethod
    def verify_correctness(self, query, result):
        raise NotImplementedError("Trouble!")

    def _extract_disjunction(self, init_predicates, core_relations, query, time_profile):  # for once
        self.or_predicates = []
        self.disjunction_cnf = None
        self.disjunction_statuses = None
        curr_eq_predicates = copy.deepcopy(init_predicates)
        all_eq_predicates = [curr_eq_predicates]
        ids = list(range(len(curr_eq_predicates)))
        if self.connectionHelper.config.detect_or:
            mode = str(getattr(self.connectionHelper.config, 'disjunction_mode', 'legacy')).lower()
            if mode in ('cnf', 'robust'):
                # CNF/robust mode: perform DB-integrated extraction that produces a
                # structured CNF (with atom witnesses/row snapshots) and legacy-
                # compatible or_predicates. Fall back to legacy loop on failure.
                try:
                    return self._extract_disjunction_cnf(init_predicates, core_relations, query, time_profile)
                except NotImplementedError:
                    # keep explicit scaffold fallback path
                    self.logger.info("CNF disjunction extraction not implemented; falling back to legacy.")
                except Exception as e:
                    self.logger.error("CNF disjunction extraction failed, falling back to legacy. ", str(e))
                self.disjunction_cnf = None
                self.disjunction_statuses = None
                self.or_predicates = []
                all_eq_predicates = [copy.deepcopy(init_predicates)]
            try:
                time_profile = self.__run_extraction_loop(all_eq_predicates, core_relations, ids, query, time_profile)
            except UnmasqueError as e:
                self.__restore_db(core_relations)
                self.update_state(ERROR)
                self.logger.error("Error in disjunction loop. ", str(e))
                raise
            except Exception as e:
                self.update_state(ERROR)
                self.logger.error("Error in disjunction loop. ", str(e))
                return False, time_profile
        self.or_predicates = list(zip(*all_eq_predicates))
        return True, time_profile

    def _extract_disjunction_cnf(self, init_predicates, core_relations, query, time_profile):
        """DB-integrated CNF extraction (incremental wiring).

        Discovers OR alternatives via the same iterative probe/mutation loop used
        by the legacy path, but also constructs a structured CNF with stable atom
        IDs and per-atom witness snapshots (`row_of`) captured from the minimized
        instance observed when each disjunct is found. Produces legacy-compatible
        `or_predicates` for downstream consumers that still rely on slot-wise
        flattening.
        """
        from ...core.disjunction.model import Atom, Clause, CNF, atom_from_legacy_pred
        try:
            from ...core.disjunction.cnf_extractor import ClauseStatus
        except Exception:
            ClauseStatus = None  # type: ignore

        curr_eq_predicates = copy.deepcopy(init_predicates)
        all_eq_predicates = [curr_eq_predicates]
        ids = list(range(len(curr_eq_predicates)))

        # Base witness snapshot corresponds to initial atoms (first-pass minimized state).
        base_snapshot = copy.deepcopy(getattr(self, 'global_min_instance_dict', None))
        all_snapshots = [[copy.deepcopy(base_snapshot) for _ in curr_eq_predicates]] if curr_eq_predicates else [[]]

        if self.connectionHelper.config.detect_or and len(curr_eq_predicates):
            time_profile = self.__run_extraction_loop(all_eq_predicates, core_relations, ids, query, time_profile,
                                                      all_snapshots=all_snapshots)

        or_predicates = list(zip(*all_eq_predicates))
        # Transpose snapshots to align with or_predicates slots (per-iteration across slots -> per-slot across iterations)
        snap_by_slot = list(zip(*all_snapshots)) if all_snapshots and all_snapshots[0] is not None else [tuple() for _ in or_predicates]

        # Build CNF: one clause per original predicate slot/position.
        clauses = []
        statuses = []
        row_of = {}
        for slot_idx, slot in enumerate(or_predicates):
            atoms = []
            slot_snaps = snap_by_slot[slot_idx] if slot_idx < len(snap_by_slot) else tuple()
            for iter_idx, pred in enumerate(slot or []):
                if not pred:
                    continue
                atom = atom_from_legacy_pred(pred)
                if atom is None:
                    # fallback: keep minimal atom shell if conversion fails
                    try:
                        atom = Atom(table=pred[0], col=pred[1])
                    except Exception:
                        continue
                atom.id = f"c{slot_idx}_a{iter_idx}"
                atoms.append(atom)
                snap = slot_snaps[iter_idx] if iter_idx < len(slot_snaps) else None
                if snap is None and iter_idx == 0:
                    snap = copy.deepcopy(base_snapshot)
                if snap is not None:
                    row_of[atom.id] = copy.deepcopy(snap)
            if atoms:
                clauses.append(Clause(id=str(slot_idx), atoms=atoms))
                if ClauseStatus is not None:
                    statuses.append(ClauseStatus(str(slot_idx), "OK"))
                else:
                    statuses.append(("OK", str(slot_idx), None))

        cnf = CNF(clauses=clauses, row_of=row_of)
        self.disjunction_cnf = cnf
        self.disjunction_statuses = statuses
        self.or_predicates = or_predicates
        return True, time_profile

    def __run_extraction_loop(self, all_eq_predicates, core_relations, ids, query, time_profile,
                              all_snapshots=None):
        """Iterative DB-integrated OR/disjunct discovery.

        If `all_snapshots` is provided (a list aligned with `all_eq_predicates`),
        per-iteration witness snapshots are recorded for each slot: for a newly
        discovered disjunct the current minimized-instance snapshot is stored,
        otherwise None. The initial snapshot entry (index 0) should be provided
        by the caller when snapshot collection is desired.
        """
        converged = False
        for _ in range(self.OR_CUTOFF):
            or_eq_predicates = []
            iter_snapshots = [] if all_snapshots is not None else None
            for i in ids:
                reference = all_eq_predicates[0][i]
                in_candidates = [copy.deepcopy(em[i]) for em in all_eq_predicates]
                self.logger.debug("Checking OR predicate of ", in_candidates)
                if not len(in_candidates[-1]):
                    or_eq_predicates.append(tuple())
                    if iter_snapshots is not None:
                        iter_snapshots.append(None)
                    continue

                restore_details = self.__get_OR_db_restoration_details(core_relations, in_candidates)
                self.logger.debug(restore_details)
                expect_populated = probe_expects_populated(restore_details)
                check, time_profile = self._mutation_pipeline(core_relations, query, time_profile, restore_details,
                                                              expect_populated=expect_populated)
                if not check or not self.__get_predicates_in_action():
                    or_eq_predicates.append(tuple())
                    if iter_snapshots is not None:
                        iter_snapshots.append(None)
                    continue
                new_predicate = self.__find_matching_predicate(self.__get_predicates_in_action(), reference, in_candidates)
                if not new_predicate or not self.__is_new_disjunct(new_predicate, in_candidates):
                    or_eq_predicates.append(tuple())
                    if iter_snapshots is not None:
                        iter_snapshots.append(None)
                else:
                    or_eq_predicates.append(new_predicate)
                    if iter_snapshots is not None:
                        iter_snapshots.append(copy.deepcopy(getattr(self, 'global_min_instance_dict', None)))
                self.logger.debug("new or predicates...", all_eq_predicates, or_eq_predicates)
            if all(element == tuple() for element in or_eq_predicates):
                converged = True
                break
            all_eq_predicates.append(or_eq_predicates)
            if all_snapshots is not None:
                all_snapshots.append(iter_snapshots)
        if not converged:
            raise UnmasqueError(ERROR_008, "DisjunctionPipeLine",
                                f"Could not determine all OR branches within {self.OR_CUTOFF} iterations.")
        return time_profile

    @staticmethod
    def __find_matching_predicate(predicates, reference, in_candidates=None):
        if not reference or not predicates:
            return tuple()
        in_candidates = in_candidates or []
        ref_key = (reference[0], reference[1])

        def _same_pred(a, b):
            if not a or not b:
                return False
            return a == b

        # Prefer same-attribute alternatives (legacy single-attribute disjunction slots).
        candidates = [pred for pred in predicates if (pred[0], pred[1]) == ref_key]
        if candidates:
            for pred in candidates:
                if len(pred) > 4 and len(reference) > 4 \
                        and pred[2] == reference[2] and pred[3] == reference[3] and pred[4] == reference[4]:
                    return pred
            for pred in candidates:
                if len(pred) > 2 and pred[2] == reference[2]:
                    return pred
            return candidates[0]

        # Cross-column clause alternative: when falsifying known slot atoms yields a
        # satisfying probe explained by a predicate on a different attribute, treat it
        # as an alternative disjunct for this slot/clause.
        existing = {(p[0], p[1], p[2], p[3], p[4]) for p in in_candidates if p and len(p) > 4}
        cross = []
        for pred in predicates:
            if not pred or len(pred) < 5:
                continue
            if (pred[0], pred[1]) == ref_key:
                continue
            key = (pred[0], pred[1], pred[2], pred[3], pred[4])
            if key in existing:
                continue
            # skip if exactly same as any in_candidate object-wise
            if any(_same_pred(pred, c) for c in in_candidates if c):
                continue
            cross.append(pred)
        if not cross:
            return tuple()
        # Prefer same table as reference for common single-table cross-column OR.
        same_table = [p for p in cross if p[0] == reference[0]]
        pool = same_table if same_table else cross
        return pool[0]

    @staticmethod
    def __get_interval(predicate):
        if not predicate or len(predicate) < 5:
            return None
        if str(predicate[2]).lower() == 'like':
            return None
        return predicate[3], predicate[4]

    @staticmethod
    def __intervals_overlap(first, second):
        first_lb, first_ub = first
        second_lb, second_ub = second
        try:
            if first_ub is not None and second_lb is not None and first_ub < second_lb:
                return False
            if second_ub is not None and first_lb is not None and second_ub < first_lb:
                return False
        except TypeError:
            return True
        return True

    def __is_new_disjunct(self, new_predicate, in_candidates):
        if not new_predicate:
            return False
        new_interval = self.__get_interval(new_predicate)
        for candidate in in_candidates:
            if not candidate:
                continue
            # exact duplicate (including cross-column same predicate form)
            if candidate == new_predicate:
                return False
            if (candidate[0], candidate[1]) != (new_predicate[0], new_predicate[1]):
                continue
            candidate_interval = self.__get_interval(candidate)
            if new_interval is None or candidate_interval is None:
                if new_predicate == candidate:
                    return False
                continue
            if self.__intervals_overlap(new_interval, candidate_interval):
                return False
        return True

    def __restore_db(self, core_relations):
        relations = getattr(self, 'all_relations', None) or core_relations
        try:
            self.connectionHelper.rollback_transaction()
        except Exception:
            pass
        try:
            sanitizer = SchemaSanitizer(self.connectionHelper, self.all_sizes)
            sanitizer.set_all_relations(list(relations))
            sanitizer.sanitize()
            self.logger.info("Database restored after disjunction extraction error.")
        except Exception as e:
            self.logger.error("Could not restore the database after disjunction extraction error. ", str(e))

    def __get_OR_db_restoration_details(self, core_relations, in_candidates):
        restore_details = []
        for tab in core_relations:
            where_condition = self.__falsify_predicates(tab, in_candidates)
            restore_details.append((tab, where_condition))
        return restore_details

    def __falsify_predicates(self, tabname, held_predicates):
        always = "true"
        where_condition = always
        wheres = []
        for pred in held_predicates:
            if not len(pred):
                return where_condition
            tab, attrib, op, lb, ub = pred[0], pred[1], pred[2], pred[3], pred[4]
            if tab != tabname:
                continue
            datatype = self.filter_extractor.get_datatype((tab, attrib))
            val_lb, val_ub = get_format(datatype, lb), get_format(datatype, ub)

            if op.lower() in ['equal', '=']:
                where_condition = f"{attrib} != {val_lb}"
            elif op.lower() == 'like':
                where_condition = f"{attrib} NOT LIKE {val_lb}"
            else:
                delta, _ = get_constants_for(datatype)
                val_lb_minus_one = get_format(datatype, get_val_plus_delta(datatype, lb, -1 * delta))
                val_ub_plus_one = get_format(datatype, get_val_plus_delta(datatype, ub, 1 * delta))
                where_condition = f"({attrib} <= {val_lb_minus_one} or {attrib} >= {val_ub_plus_one})"
            wheres.append(where_condition)
        where_condition = " and ".join(wheres) if len(wheres) else always
        self.logger.debug(where_condition)
        return where_condition

    @abstractmethod
    def extract(self, query):
        pass