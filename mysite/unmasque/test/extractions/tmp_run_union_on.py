"""Temporary runner: run a main_cmd workload with union detection forced on.

Used only to measure MQ18 with the union pipeline enabled.  Deleted after use.
"""
from pathlib import Path
import sys

qid = sys.argv[1]
sys.argv = ["main_cmd", qid]

repo_root = Path(__file__).resolve().parents[3]
src_path = str(repo_root / "mysite" / "unmasque" / "src" / "main_cmd.py")
with open(src_path) as f:
    code = f.read()
code = code.replace("conn.config.detect_union = hq.union",
                    "conn.config.detect_union = True")
exec(compile(code, src_path, "exec"),
     {"__name__": "__main__", "__file__": src_path,
      "__package__": "mysite.unmasque.src"})
