import copy
import time

from ..core.dataclass.genPipeline_context import GenPipelineContext
from ..core.dataclass.pgao_context import PGAOcontext
from ...src.pipeline.fragments.DisjunctionPipeLine import DisjunctionPipeLine
from ...src.pipeline.fragments.NepPipeLine import NepPipeLine
from .abstract.generic_pipeline import GenericPipeLine
from ..core.elapsed_time import create_zero_time_profile
from ..util.constants import FROM_CLAUSE, START, DONE, RUNNING, PROJECTION, \
    GROUP_BY, AGGREGATE, ORDER_BY, LIMIT, UNION, ERROR, OK, INIT
from ...src.core.aggregation import Aggregation
from ...src.core.from_clause import FromClause
from ...src.core.groupby_clause import GroupBy
from ...src.core.initialization import Initiator
from ...src.core.limit import Limit
from ...src.core.orderby_clause import OrderBy
from ...src.core.projection import Projection


class IOState:
    def __init__(self, inp, output):
        self.input = inp
        self.output = output
        self.dic = {
            "input": self.input,
            "output": self.output
        }

    def get_dic(self):
        return self.dic


class ExtractionPipeLine(DisjunctionPipeLine,
                         NepPipeLine):

    def __init__(self, connectionHelper, name="Extraction PipeLine"):
        DisjunctionPipeLine.__init__(self, connectionHelper, name)
        NepPipeLine.__init__(self, connectionHelper)
        self.genPipelineCtx = None
        self.pj = None
        self.global_pk_dict = None
        self.pgao_ctx = PGAOcontext()
        self.initiator = None
        self.disjunction_cnf = None
        self.disjunction_statuses = None

    def _run_initiator(self, query):
        """Run the initiator as its own pipeline stage.

        The initiator prepares the working schema, metadata, backup, and table
        sizes. It must finish before From Clause extraction starts, and its time
        must not be attributed to the From Clause stage. Running it here also
        keeps its work out of Union's From Clause timing.

        Returns (success, error_message).
        """
        initiator = Initiator(self.connectionHelper)
        check = initiator.result
        init_ran = not initiator.done
        if init_ran:
            check = initiator.doJob(query)
            if initiator.local_elapsed_time is not None:
                self.time_profile.update_for_init(initiator.local_elapsed_time, 0)
        self.initiator = initiator

        if not initiator.done or not check:
            error = check if isinstance(check, str) else "Database initialization failed."
            return False, error
        return True, None

    def process(self, query: str):
        return GenericPipeLine.process(self, query)

    def doJob(self, query, qe=None):
        return GenericPipeLine.doJob(self, query, qe)

    def verify_correctness(self, query, result):
        GenericPipeLine.verify_correctness(self, query, result)

    def extract(self, query):
        self.connectionHelper.connectUsingParams()
        self.info[UNION] = "SKIPPED"

        '''
        Initialization
        '''
        check, init_error = self._run_initiator(query)
        if not check:
            self.error = init_error
            self.logger.error(self.error)
            self.update_state(ERROR)
            self.info[INIT] = None
            return None
        self.info[INIT] = {'relations': self.initiator.all_relations,
                           'sizes': self.initiator.all_sizes}

        '''
        From Clause Extraction
        '''
        self.update_state(FROM_CLAUSE + START)
        fc = FromClause(self.connectionHelper, self.initiator)
        fc.reset_data_schema()
        self.update_state(FROM_CLAUSE + RUNNING)
        check = fc.doJob(query)
        self.update_state(FROM_CLAUSE + DONE)
        self.time_profile.update_for_from_clause(fc.local_elapsed_time, fc.app_calls)
        io = IOState(query, fc.core_relations)
        if not check or not fc.done:
            self.error = "" if check else (self.error_string or "")
            self.logger.error(self.error)
            self.update_state(ERROR)
            self.info[FROM_CLAUSE] = None
            io.output = ""
            return None
        self.info[FROM_CLAUSE] = fc.core_relations
        self.IO[FROM_CLAUSE] = io.get_dic()
        self.core_relations = fc.core_relations
        self.all_sizes = self.initiator.all_sizes
        self.key_lists = self.initiator.global_key_lists
        self.global_pk_dict = self.initiator.global_pk_dict

        # The probing above renames tables inside the user schema and always
        # rolls the transaction back. Only after it has completed do we create
        # working-schema backups, and only for the core relations that were
        # actually identified. This keeps the backup minimal and guarantees the
        # user schema is never used as a scratch area by mistake. The backup is
        # pure overhead of the pipeline: it is deliberately NOT attributed to
        # any stage (only the end-to-end wall-clock time includes it), so stage
        # timings reflect extraction work rather than table copying.
        if not fc.init.backup_done and fc.core_relations:
            if not self.connectionHelper.config.use_cs2 and \
                    not self.connectionHelper.config.scale_down:
                backup_start = time.time()
                fc.init.take_backup(self.core_relations)
                fc.init.backup_done = True
                backup_duration = time.time() - backup_start
                self.time_profile.update_for_backup(backup_duration)
                self.logger.debug(
                    f"Core-relation backup took {backup_duration:.2f}s "
                    "(wall-clock only, not attributed to any stage)")

        eq = self._after_from_clause_extract(query, self.core_relations)
        self.connectionHelper.closeConnection()
        return eq

    def _after_from_clause_extract(self, query, core_relations):

        time_profile = create_zero_time_profile()

        check, time_profile = self._mutation_pipeline(core_relations, query, time_profile)
        if not check:
            # self.error += OK
            self.logger.error(self.error)
            self.update_state(ERROR)
            self.time_profile.update(time_profile)
            return None

        check, time_profile = self._extract_disjunction(self.aoa.arithmetic_filters,
                                                        core_relations, query, time_profile)
        if not check:
            # self.error += OK
            self.logger.error(self.error)
            self.update_state(ERROR)
            self.time_profile.update(time_profile)
            return None

        self.time_profile.update(time_profile)
        self.__gen_pipeline_preprocess(core_relations)

        '''
        Projection Extraction
        '''
        self.update_state(PROJECTION + START)
        self.pj = Projection(self.connectionHelper, self.genPipelineCtx)

        self.update_state(PROJECTION + RUNNING)
        check = self.pj.doJob(query)
        self.update_state(PROJECTION + DONE)
        self.time_profile.update_for_projection(self.pj.local_elapsed_time, self.pj.app_calls)
        self.info[PROJECTION] = {'names': self.pj.projection_names, 'attribs': self.pj.projected_attribs}
        if not check:
            self.update_state(ERROR)
            self.info[PROJECTION] = None
            self.logger.error("Cannot find projected attributes. ")
            return None
        if not self.pj.done:
            self.update_state(ERROR)
            self.info[PROJECTION] = None
            self.error = "" if check else (self.error_string or "")
            self.logger.error(self.error)
            return None
        self.pgao_ctx.projection = self.pj

        self.update_state(GROUP_BY + START)
        gb = GroupBy(self.connectionHelper, self.genPipelineCtx, self.pgao_ctx)
        self.update_state(GROUP_BY + RUNNING)
        check = gb.doJob(query)
        self.update_state(GROUP_BY + DONE)
        self.time_profile.update_for_group_by(gb.local_elapsed_time, gb.app_calls)
        self.info[GROUP_BY] = gb.group_by_attrib
        if not check:
            self.update_state(ERROR)
            self.info[GROUP_BY] = None
            self.logger.info("Cannot find group by attributes. ")
        if not gb.done:
            self.update_state(ERROR)
            self.info[GROUP_BY] = None
            self.error = "" if check else (self.error_string or "")
            self.logger.error(self.error)
            return None
        self.pgao_ctx.group_by = gb

        self.update_state(AGGREGATE + START)
        agg = Aggregation(self.connectionHelper, self.genPipelineCtx, self.pgao_ctx)
        self.update_state(AGGREGATE + RUNNING)
        check = agg.doJob(query)
        self.update_state(AGGREGATE + DONE)
        self.time_profile.update_for_aggregate(agg.local_elapsed_time, agg.app_calls)
        self.info[AGGREGATE] = agg.global_aggregated_attributes
        if not check:
            self.update_state(ERROR)
            self.info[AGGREGATE] = None
            self.logger.info("Cannot find aggregations.")
        if not agg.done:
            self.update_state(ERROR)
            self.info[AGGREGATE] = None
            self.error = "" if check else (self.error_string or "")
            self.logger.error(self.error)
            return None
        self.pgao_ctx.aggregate = agg

        self.update_state(ORDER_BY + START)
        ob = OrderBy(self.connectionHelper, self.genPipelineCtx, self.pgao_ctx)
        self.update_state(ORDER_BY + RUNNING)
        ob.doJob(query)
        self.update_state(ORDER_BY + DONE)
        self.time_profile.update_for_order_by(ob.local_elapsed_time, ob.app_calls)
        self.info[ORDER_BY] = ob.orderBy_string
        if not ob.has_orderBy:
            self.update_state(ERROR)
            self.info[ORDER_BY] = None
            self.logger.info("Cannot find aggregations.")
        if not ob.done:
            self.update_state(ERROR)
            self.info[ORDER_BY] = None
            self.error = "" if check else (self.error_string or "")
            self.logger.error(self.error)
            return None
        self.pgao_ctx.order_by = ob

        self.update_state(LIMIT + START)
        lm = Limit(self.connectionHelper, self.genPipelineCtx, self.pgao_ctx)
        self.update_state(LIMIT + RUNNING)
        lm.doJob(query)
        self.update_state(LIMIT + DONE)
        self.time_profile.update_for_limit(lm.local_elapsed_time, lm.app_calls)
        self.info[LIMIT] = lm.limit
        if lm.limit is None:
            self.update_state(ERROR)
            self.info[LIMIT] = None
            self.logger.info("Cannot find limit.")
        if not lm.done:
            self.update_state(ERROR)
            self.info[LIMIT] = None
            self.error = "" if check else (self.error_string or "")
            self.logger.error(self.error)
            return None

        self.q_generator.get_datatype = self.filter_extractor.get_datatype  # method
        self.q_generator.from_clause = core_relations
        self.q_generator.algebraic_predicates = self.aoa
        self.q_generator.arithmetic_disjunctions = self.genPipelineCtx

        self.q_generator.pgaoCtx = self.pgao_ctx
        self.q_generator.limit = lm
        eq = self.q_generator.formulate_query_string()
        self.logger.debug("extracted query:\n", eq)

        eq = self._extract_NEP(core_relations, self.all_sizes, query, self.genPipelineCtx)
        return eq

    def __gen_pipeline_preprocess(self, core_relations):
        self.logger.debug("aoa post-process.")
        self.genPipelineCtx = GenPipelineContext(core_relations, self.aoa,
                                                 self.filter_extractor, self.global_min_instance_dict,
                                                 self.or_predicates,
                                                 cnf=getattr(self, 'disjunction_cnf', None))
        self.logger.debug(self.genPipelineCtx.arithmetic_filters)
        self.logger.debug(self.genPipelineCtx.global_join_graph)
        self.logger.debug(self.genPipelineCtx.filter_in_predicates)
        self.logger.debug(self.genPipelineCtx.filter_attrib_dict)
        self.genPipelineCtx.doJob()
        self.logger.debug("after doJob...")
        self.logger.debug(self.genPipelineCtx.arithmetic_filters)
        self.logger.debug(self.genPipelineCtx.global_join_graph)
        self.logger.debug(self.genPipelineCtx.filter_in_predicates)
        self.logger.debug(self.genPipelineCtx.filter_attrib_dict)
