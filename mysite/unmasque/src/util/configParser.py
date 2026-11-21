import configparser
from pathlib import Path

from .application_type import ApplicationType
from .constants import DATABASE_SECTION, HOST, PORT, USER, PASSWORD, SCHEMA, DBNAME, \
    SUPPORT_SECTION, LEVEL, LOGGING_SECTION, FEATURE_SECTION, DETECT_UNION, DETECT_NEP, USE_CS2, DATABASE, DETECT_OR, \
    DETECT_OJ, LIMIT, OPTIONS_SECTION, DOWN_SCALE, WORKING_SCHEMA, TABLE_SIZE_SECTION, TABLE, SCALE_FACTOR, SCALE_RETRY, \
    USE_INDEX


class Config:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # default values
        self.use_index = False
        self.scale_retry = 0
        self.sf = 1  # Default 1
        self.workmem = '32MB'
        self.limit_limit = 1000
        self.database = "postgres"
        # self.index_maker = "create_indexes.sql"
        self.pkfk = "pkfkrelations.csv"
        self.schema = WORKING_SCHEMA
        self.user_schema = "public"
        self.dbname = "tpch"
        self.port = "5432"
        self.password = "postgres"
        self.user = "postgres"
        self.host = "localhost"
        self.log_level = 'INFO'
        self.base_path = Path(__file__).parent.parent.parent.parent
        self.config_loaded = False
        self.detect_union = False
        self.detect_nep = False
        self.detect_or = False
        self.detect_oj = False
        self.use_cs2 = False
        self.scale_down = False
        # Disjunction/CNF extraction mode scaffolding (step 1, inert by default).
        # 'legacy' preserves current detect_or behavior.
        self.disjunction_mode = "legacy"
        # Step 7 diagnostics/hardening knobs (optional, safe defaults).
        self.disjunction_max_iters = 10000
        self.disjunction_max_routes = 128
        self.disjunction_diagnostics = True
        # Minimizer selection: view (default), copy, pk, hybrid.
        self.minimizer = "view"
        self.app_type = ApplicationType.SQL_ERR_FWD
        self.database = "postgres"
        self.table_sizes_dict = {}

    def parse_config(self):
        if self.config_loaded:
            return

        try:
            config_file = (self.base_path / "config.ini").resolve()
            config_object = configparser.ConfigParser()
            with open(config_file, "r") as file_object:
                config_object.read_file(file_object)
                self.database = config_object.get(DATABASE_SECTION, DATABASE)
                self.host = config_object.get(DATABASE_SECTION, HOST)
                self.port = config_object.get(DATABASE_SECTION, PORT)
                self.user = config_object.get(DATABASE_SECTION, USER)
                self.password = config_object.get(DATABASE_SECTION, PASSWORD)
                self.dbname = config_object.get(DATABASE_SECTION, DBNAME)
                self.user_schema = config_object.get(DATABASE_SECTION, SCHEMA)
                i = 1
                while True:
                    try:
                        table_size_entry = config_object.get(TABLE_SIZE_SECTION, TABLE + str(i))
                        key, value = table_size_entry.split(":")
                        self.table_sizes_dict[key.strip()] = int(value.strip())
                        i = i + 1
                    except Exception:
                        break

                self.pkfk = config_object.get(SUPPORT_SECTION, "pkfk")
                # self.index_maker = config_object.get(SUPPORT_SECTION, "index_maker")

                self.log_level = config_object.get(LOGGING_SECTION, LEVEL)

                self.config_optional_features(config_object)

        except FileNotFoundError:
            print("config.ini not found. Default configs loaded!")
        except KeyError:
            print(" config not found. Using default config!")

        self.config_loaded = True

    def config_optional_features(self, config_object):
        detect_union = config_object.get(FEATURE_SECTION, DETECT_UNION)
        if detect_union.lower() == "no":
            self.detect_union = False
        elif detect_union.lower() == "yes":
            self.detect_union = True

        detect_nep = config_object.get(FEATURE_SECTION, DETECT_NEP)
        if detect_nep.lower() == "no":
            self.detect_nep = False
        elif detect_nep.lower() == "yes":
            self.detect_nep = True

        use_cs2 = config_object.get(FEATURE_SECTION, USE_CS2)
        if use_cs2.lower() == "no":
            self.use_cs2 = False
        elif use_cs2.lower() == "yes":
            self.use_cs2 = True

        detect_or = config_object.get(FEATURE_SECTION, DETECT_OR)
        if detect_or.lower() == "no":
            self.detect_or = False
        elif detect_or.lower() == "yes":
            self.detect_or = True

        # Optional scaffolding flag for future CNF disjunction implementation.
        # Kept backward-compatible: missing/unknown values default to legacy.
        try:
            disjunction_mode = config_object.get(FEATURE_SECTION, "disjunction_mode", fallback="legacy")
            if str(disjunction_mode).lower() in ("legacy", "cnf", "robust"):
                self.disjunction_mode = str(disjunction_mode).lower()
            else:
                self.disjunction_mode = "legacy"
        except Exception:
            self.disjunction_mode = "legacy"
        # Optional Step 7 diagnostics/hardening config (safe defaults on missing/invalid).
        try:
            self.disjunction_max_iters = max(1, int(config_object.get(FEATURE_SECTION, "disjunction_max_iters", fallback=self.disjunction_max_iters)))
        except Exception:
            self.disjunction_max_iters = 10000
        try:
            self.disjunction_max_routes = max(1, int(config_object.get(FEATURE_SECTION, "disjunction_max_routes", fallback=self.disjunction_max_routes)))
        except Exception:
            self.disjunction_max_routes = 128
        try:
            diag = config_object.get(FEATURE_SECTION, "disjunction_diagnostics", fallback="yes")
            self.disjunction_diagnostics = str(diag).lower() not in ("no", "false", "0", "off")
        except Exception:
            self.disjunction_diagnostics = True
        try:
            minimizer = str(config_object.get(FEATURE_SECTION, "minimizer", fallback=self.minimizer)).lower().strip()
            aliases = {
                "view": "view",
                "view_minimizer": "view",
                "copy": "copy",
                "copy_based": "copy",
                "copybased": "copy",
                "pk": "pk",
                "pk_view": "pk",
                "pkview": "pk",
                "hybrid": "hybrid",
            }
            self.minimizer = aliases.get(minimizer, "view")
        except Exception:
            self.minimizer = "view"

        detect_oj = config_object.get(FEATURE_SECTION, DETECT_OJ)
        if detect_oj.lower() == "no":
            self.detect_oj = False
        elif detect_oj.lower() == "yes":
            self.detect_oj = True

        self.load_optionals(config_object)

    def load_optionals(self, config_object):
        try:
            limit_config = config_object.get(OPTIONS_SECTION, LIMIT.lower())
            self.limit_limit = int(limit_config)
        except:
            pass
        try:
            downscale = config_object.get(OPTIONS_SECTION, DOWN_SCALE.lower())
            self.scale_down = downscale.lower() == 'yes'
        except:
            pass

        try:
            scale_factor = config_object.get(OPTIONS_SECTION, SCALE_FACTOR)
            self.sf = int(scale_factor)
        except:
            pass

        try:
            retry_scale_down = config_object.get(OPTIONS_SECTION, SCALE_RETRY)
            self.scale_retry = int(retry_scale_down)
        except:
            pass

        try:
            use_index = config_object.get(OPTIONS_SECTION, USE_INDEX)
            self.use_index = use_index == 'yes'
        except:
            pass
