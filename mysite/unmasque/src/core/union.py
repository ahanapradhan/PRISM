from . import algorithm1
from .union_from_clause import UnionFromClause
from ...src.core.abstract.AppExtractorBase import AppExtractorBase


class Union(AppExtractorBase):

    def __init__(self, connectionHelper):
        super().__init__(connectionHelper, "Union")
        self.key_lists = None
        self.all_relations = None
        self.init_elapsed_time = 0
        self.init_app_calls = 0
        self.enabled = self.connectionHelper.config.detect_union

    def extract_params_from_args(self, args):
        return args[0]

    def doActualJob(self, args=None):
        query = self.extract_params_from_args(args)
        db = UnionFromClause(self.connectionHelper)
        db.reset_data_schema()
        init_was_done = db.fromClause.init.done
        p, pstr, union_profile = algorithm1.algo(db, query)
        # Initiator runs inside the union extraction's from-clause probe. Record
        # its one-time pre-extraction cost so the pipeline can report it apart
        # from the Union/From Clause module rows.
        if not init_was_done and db.fromClause.init.local_elapsed_time is not None:
            self.init_elapsed_time = db.fromClause.init.local_elapsed_time
            # App-call counts are diagnostic stats only. Not every extractor
            # tracks them (Initiator does not), and a missing counter must never
            # break extraction.
            self.init_app_calls = getattr(db.fromClause.init, "app_calls", 0) or 0
        self.all_relations = db.get_relations()
        self.all_sizes = db.get_all_sizes()
        self.key_lists = db.fromClause.init.global_key_lists
        return p, pstr, union_profile



