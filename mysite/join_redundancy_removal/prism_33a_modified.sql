-- createdb prism_33a
-- pg_dump --schema-only --no-owner --no-privileges prism_10a \
-- | psql -v ON_ERROR_STOP=1 -d prism_33a

psql -v ON_ERROR_STOP=1 -d prism_33a <<'SQL'
BEGIN;

TRUNCATE TABLE
    company_name,
    company_type,
    info_type,
    kind_type,
    link_type,
    movie_companies,
    movie_info_idx,
    movie_link,
    title
CASCADE;

-- ---------------------------------------------------------
-- Dimension and lookup tables (Exactly 1 row each)
-- ---------------------------------------------------------
INSERT INTO company_type (id, kind) VALUES (1, 'production companies');
INSERT INTO kind_type (id, kind) VALUES (1, 'tv series');
INSERT INTO info_type (id, info) VALUES (1, 'rating');
INSERT INTO link_type (id, link) VALUES (1, 'sequel');
INSERT INTO company_name (id, name, country_code) VALUES (1, 'Minimal US Corp', '[us]');

-- ---------------------------------------------------------
-- Central title (Exactly 1 row)
-- Satisfies production_year BETWEEN 2005 AND 2008
-- ---------------------------------------------------------
INSERT INTO title (id, title, kind_id, production_year) VALUES (1, 'Minimal TV Series', 1, 2006);

-- ---------------------------------------------------------
-- Linking and info tables (Exactly 1 row per table)
-- ---------------------------------------------------------
-- Rating < 3.0
INSERT INTO movie_info_idx (id, movie_id, info_type_id, info) VALUES (1, 1, 1, '2.5');

-- Company Link
INSERT INTO movie_companies (id, movie_id, company_id, company_type_id) VALUES (1, 1, 1, 1);

-- Self-linking movie (movie_id and linked_movie_id are both 1)
INSERT INTO movie_link (id, movie_id, linked_movie_id, link_type_id) VALUES (1, 1, 1, 1);

COMMIT;

-- ---------------------------------------------------------
-- Verify all tables have exactly 1 row
-- ---------------------------------------------------------
SELECT 'company_name' AS table_name, COUNT(*) AS row_count FROM company_name
UNION ALL SELECT 'company_type', COUNT(*) FROM company_type
UNION ALL SELECT 'info_type', COUNT(*) FROM info_type
UNION ALL SELECT 'kind_type', COUNT(*) FROM kind_type
UNION ALL SELECT 'link_type', COUNT(*) FROM link_type
UNION ALL SELECT 'movie_companies', COUNT(*) FROM movie_companies
UNION ALL SELECT 'movie_info_idx', COUNT(*) FROM movie_info_idx
UNION ALL SELECT 'movie_link', COUNT(*) FROM movie_link
UNION ALL SELECT 'title', COUNT(*) FROM title
ORDER BY table_name;
SQL

-- Flags: Scale Down False, Union False, OJ False, NEP False, CS2 False
-- Extraction Pipeline
-- seed_sample_size_per 0.32
-- Start from 14:10:04.004209
-- /Users/akshay/Documents/Semesters/Sem5/ADBMS/PRISM/mysite/unmasque/src/core/view_minimizer.py:132:UserWarning: pandas only supports SQLAlchemy connectable (engine/connection) or database string URI or sqlite3 DBAPI2 connection. Other DBAPI2 objects are not tested. Please consider using SQLAlchemy.
--   sql_query = pd.read_sql_query(self.connectionHelper.queries.get_star(tabname), self.connectionHelper.conn)
-- ============= Given Query ===============
-- SELECT cn.name AS company,
--        mi_idx.info AS rating,
--        t.title AS movie
-- FROM company_name AS cn,
--      info_type AS it,
--      kind_type AS kt,
--      link_type AS lt,
--      movie_companies AS mc,
--      movie_info_idx AS mi_idx,
--      movie_link AS ml,
--      title AS t
-- WHERE cn.country_code = '[us]'
--   AND it.info = 'rating'
--   AND kt.kind = 'tv series'
--   AND lt.link = 'sequel'
--   AND t.production_year BETWEEN 2005 AND 2008
--   -- ----------------------------------------------------
--   -- Core Tree Joins
--   -- ----------------------------------------------------
--   AND lt.id = ml.link_type_id
--   AND it.id = mi_idx.info_type_id
--   AND kt.id = t.kind_id
--   AND cn.id = mc.company_id
--   -- ----------------------------------------------------
--   -- Redundant "Complete Graph" Joins on movie_id
--   -- ----------------------------------------------------
--   AND t.id = ml.movie_id
--   AND t.id = ml.linked_movie_id
--   AND t.id = mi_idx.movie_id
--   AND t.id = mc.movie_id
--   AND ml.movie_id = mi_idx.movie_id
--   AND ml.movie_id = mc.movie_id
--   AND mi_idx.movie_id = mc.movie_id
--   AND ml.linked_movie_id = mi_idx.movie_id
--   AND ml.linked_movie_id = mc.movie_id;
    
-- =========== Extracted Query =============
 
--  Select company_name.name as company, movie_info_idx.info as rating, title.title as movie 
--  From company_name, info_type, kind_type, link_type, movie_companies, movie_info_idx, movie_link, title 
--  Where movie_companies.movie_id = movie_info_idx.movie_id
--  and movie_info_idx.movie_id = movie_link.linked_movie_id
--  and movie_link.linked_movie_id = movie_link.movie_id
--  and movie_link.movie_id = title.id
--  and link_type.id = movie_link.link_type_id
--  and kind_type.id = title.kind_id
--  and company_name.id = movie_companies.company_id
--  and info_type.id = movie_info_idx.info_type_id
--  and company_name.country_code = '[us]'
--  and info_type.info = 'rating'
--  and kind_type.kind = 'tv series'
--  and link_type.link = 'sequel'
--  and title.production_year between 2005 and 2008;
-- ================ Profile ================
-- ╒══════════════════════╤════════════╤═════════╕
-- │ Step                 │   Time (s) │   Total │
-- ╞══════════════════════╪════════════╪═════════╡
-- │ From Clause:         │       0.03 │      21 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Union:               │       0    │       0 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Restore DB:          │       0.01 │       0 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Correlated Sampling: │       0    │       0 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ View Minimization:   │       0.05 │       9 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Where Clause:        │       4.02 │    1647 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Projection:          │       0.15 │      70 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Group BY:            │       0.53 │      39 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Aggregation:         │       0.08 │       3 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Order by:            │       0.11 │       6 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Limit:               │       2.99 │       8 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Outer Join:          │       0    │       0 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ NEP:                 │       0    │       0 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Result               │       0.02 │       1 │
-- │  Comparator:         │            │         │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Total:               │       8.16 │    1804 │
-- ╘══════════════════════╧════════════╧═════════╛
