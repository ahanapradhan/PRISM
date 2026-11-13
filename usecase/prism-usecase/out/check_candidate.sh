#!/usr/bin/env bash
# Usage: PGUSER=.. PGPASSWORD=.. PGDATABASE=.. ./check_candidate.sh candidate.sql
# Runs an LLM's candidate query and compares it with the application's real output.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cand="${1:?usage: check_candidate.sh candidate.sql}"
export PGHOST="${PGHOST:-localhost}" PGPORT="${PGPORT:-5432}" PGUSER="${PGUSER:-$(whoami)}"
if ! psql -At -F $'\t' -P null=NULL -v ON_ERROR_STOP=1 -f "$cand" > "$HERE/candidate_out.txt" 2> "$HERE/candidate_err.txt"; then
  echo "CANDIDATE FAILED TO RUN:"; cat "$HERE/candidate_err.txt"; exit 2; fi
cr=$(wc -l < "$HERE/candidate_out.txt" | xargs); cc=$(head -n1 "$HERE/candidate_out.txt" | awk -F'\t' '{print NF}')
er=$(wc -l < "$HERE/result_java.txt" | xargs);   ec=$(head -n1 "$HERE/result_java.txt" | awk -F'\t' '{print NF}')
echo "candidate: $cr rows x ${cc:-0} columns | expected: $er rows x $ec columns"
if cmp -s "$HERE/candidate_out.txt" "$HERE/result_java.txt"; then echo "EXACT MATCH"
elif diff -q <(sort "$HERE/candidate_out.txt") <(sort "$HERE/result_java.txt") >/dev/null; then echo "SAME ROWS, DIFFERENT ORDER"
else echo "DIFFERENT"; diff <(sort "$HERE/candidate_out.txt") <(sort "$HERE/result_java.txt") | head -n 20; fi
