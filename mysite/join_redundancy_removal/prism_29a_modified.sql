createdb prism_29a
pg_dump --schema-only --no-owner --no-privileges prism_10a \
| psql -v ON_ERROR_STOP=1 -d prism_29a

-- psql -v ON_ERROR_STOP=1 -d prism_29a <<'SQL'
-- BEGIN;

-- TRUNCATE TABLE
--     aka_name,
--     cast_info,
--     char_name,
--     comp_cast_type,
--     company_name,
--     company_type,
--     complete_cast,
--     info_type,
--     keyword,
--     movie_companies,
--     movie_info,
--     movie_keyword,
--     name,
--     person_info,
--     role_type,
--     title
-- CASCADE;

-- -- ---------------------------------------------------------
-- -- Dimension and lookup tables
-- -- ---------------------------------------------------------

-- INSERT INTO comp_cast_type (id, kind) VALUES (1, 'cast');
-- INSERT INTO char_name (id, name) VALUES (1, 'Queen');
-- INSERT INTO company_name (id, name, country_code) VALUES (1, 'DreamWorks', '[us]');
-- INSERT INTO company_type (id, kind) VALUES (1, 'production companies');
-- INSERT INTO info_type (id, info) VALUES (1, 'release dates');
-- INSERT INTO keyword (id, keyword) VALUES (1, 'computer-animation');
-- INSERT INTO role_type (id, role) VALUES (1, 'actress');

-- -- ---------------------------------------------------------
-- -- Central title row
-- -- ---------------------------------------------------------

-- INSERT INTO title (id, title, kind_id, production_year) VALUES
--     (1, 'Shrek 2', 1, 2004);

-- -- ---------------------------------------------------------
-- -- Person (Actress) & AKA Names (2 alias rows for cross product)
-- -- ---------------------------------------------------------

-- INSERT INTO name (id, name, gender) VALUES
--     (1, 'Ann, The Single Actress', 'f');

-- INSERT INTO aka_name (id, person_id, name) VALUES
--     (1, 1, 'Annie Alias One'),
--     (2, 1, 'Annie Alias Two');

-- -- ---------------------------------------------------------
-- -- Person Info 
-- -- Using info_type_id = 1 to satisfy the NOT NULL constraint
-- -- ---------------------------------------------------------

-- INSERT INTO person_info (id, person_id, info_type_id, info) VALUES
--     (1, 1, 1, 'Random Trivia');

-- -- ---------------------------------------------------------
-- -- Movie Info (2 rows to multiply with the aliases)
-- -- ---------------------------------------------------------

-- INSERT INTO movie_info (id, movie_id, info_type_id, info) VALUES
--     (1, 1, 1, 'Japan: 2004-05-15'),
--     (2, 1, 1, 'USA: 2004-05-19');

-- -- ---------------------------------------------------------
-- -- Complete Cast & Movie Links
-- -- Using dummy IDs (1) to satisfy NOT NULL constraints
-- -- ---------------------------------------------------------

-- INSERT INTO complete_cast (id, movie_id, subject_id, status_id) VALUES (1, 1, 1, 1);
-- INSERT INTO movie_companies (id, movie_id, company_id, company_type_id) VALUES (1, 1, 1, 1);
-- INSERT INTO movie_keyword (id, movie_id, keyword_id) VALUES (1, 1, 1);

-- -- ---------------------------------------------------------
-- -- Cast Info (3 rows to multiply the cross product further)
-- -- ---------------------------------------------------------

-- INSERT INTO cast_info (id, person_id, movie_id, person_role_id, role_id, note) VALUES
--     (1, 1, 1, 1, 1, '(voice)'),
--     (2, 1, 1, 1, 1, '(voice) (uncredited)'),
--     (3, 1, 1, 1, 1, '(voice: English version)');

-- COMMIT;

-- -- ---------------------------------------------------------
-- -- Verify the table sizes
-- -- ---------------------------------------------------------

-- SELECT 'aka_name' AS table_name, COUNT(*) AS row_count FROM aka_name
-- UNION ALL SELECT 'cast_info', COUNT(*) FROM cast_info
-- UNION ALL SELECT 'char_name', COUNT(*) FROM char_name
-- UNION ALL SELECT 'comp_cast_type', COUNT(*) FROM comp_cast_type
-- UNION ALL SELECT 'company_name', COUNT(*) FROM company_name
-- UNION ALL SELECT 'company_type', COUNT(*) FROM company_type
-- UNION ALL SELECT 'complete_cast', COUNT(*) FROM complete_cast
-- UNION ALL SELECT 'info_type', COUNT(*) FROM info_type
-- UNION ALL SELECT 'keyword', COUNT(*) FROM keyword
-- UNION ALL SELECT 'movie_companies', COUNT(*) FROM movie_companies
-- UNION ALL SELECT 'movie_info', COUNT(*) FROM movie_info
-- UNION ALL SELECT 'movie_keyword', COUNT(*) FROM movie_keyword
-- UNION ALL SELECT 'name', COUNT(*) FROM name
-- UNION ALL SELECT 'person_info', COUNT(*) FROM person_info
-- UNION ALL SELECT 'role_type', COUNT(*) FROM role_type
-- UNION ALL SELECT 'title', COUNT(*) FROM title
-- ORDER BY table_name;
-- SQL

psql -v ON_ERROR_STOP=1 -d prism_29a <<'SQL'
BEGIN;

TRUNCATE TABLE
    aka_name,
    cast_info,
    char_name,
    comp_cast_type,
    company_name,
    company_type,
    complete_cast,
    info_type,
    keyword,
    movie_companies,
    movie_info,
    movie_keyword,
    name,
    person_info,
    role_type,
    title
CASCADE;

-- ---------------------------------------------------------
-- Dimension and lookup tables (Exactly 1 row each)
-- ---------------------------------------------------------
INSERT INTO comp_cast_type (id, kind) VALUES (1, 'cast');
INSERT INTO char_name (id, name) VALUES (1, 'Queen');
INSERT INTO company_name (id, name, country_code) VALUES (1, 'DreamWorks', '[us]');
INSERT INTO company_type (id, kind) VALUES (1, 'production companies');
INSERT INTO info_type (id, info) VALUES (1, 'release dates');
INSERT INTO keyword (id, keyword) VALUES (1, 'computer-animation');
INSERT INTO role_type (id, role) VALUES (1, 'actress');

-- ---------------------------------------------------------
-- Central title (Exactly 1 row)
-- ---------------------------------------------------------
INSERT INTO title (id, title, kind_id, production_year) VALUES (1, 'Shrek 2', 1, 2004);

-- ---------------------------------------------------------
-- Person details (Exactly 1 row per table)
-- ---------------------------------------------------------
INSERT INTO name (id, name, gender) VALUES (1, 'Ann, The Single Actress', 'f');
INSERT INTO aka_name (id, person_id, name) VALUES (1, 1, 'Annie Alias');
INSERT INTO person_info (id, person_id, info_type_id, info) VALUES (1, 1, 1, 'Random Trivia');

-- ---------------------------------------------------------
-- Movie details (Exactly 1 row per table)
-- ---------------------------------------------------------
INSERT INTO movie_info (id, movie_id, info_type_id, info) VALUES (1, 1, 1, 'USA: 2004-05-19');

-- ---------------------------------------------------------
-- Linking and cast tables (Exactly 1 row per table)
-- ---------------------------------------------------------
INSERT INTO complete_cast (id, movie_id, subject_id, status_id) VALUES (1, 1, 1, 1);
INSERT INTO movie_companies (id, movie_id, company_id, company_type_id) VALUES (1, 1, 1, 1);
INSERT INTO movie_keyword (id, movie_id, keyword_id) VALUES (1, 1, 1);
INSERT INTO cast_info (id, person_id, movie_id, person_role_id, role_id, note) VALUES (1, 1, 1, 1, 1, '(voice)');

COMMIT;

-- ---------------------------------------------------------
-- Verify all tables have exactly 1 row
-- ---------------------------------------------------------
SELECT 'aka_name' AS table_name, COUNT(*) AS row_count FROM aka_name
UNION ALL SELECT 'cast_info', COUNT(*) FROM cast_info
UNION ALL SELECT 'char_name', COUNT(*) FROM char_name
UNION ALL SELECT 'comp_cast_type', COUNT(*) FROM comp_cast_type
UNION ALL SELECT 'company_name', COUNT(*) FROM company_name
UNION ALL SELECT 'company_type', COUNT(*) FROM company_type
UNION ALL SELECT 'complete_cast', COUNT(*) FROM complete_cast
UNION ALL SELECT 'info_type', COUNT(*) FROM info_type
UNION ALL SELECT 'keyword', COUNT(*) FROM keyword
UNION ALL SELECT 'movie_companies', COUNT(*) FROM movie_companies
UNION ALL SELECT 'movie_info', COUNT(*) FROM movie_info
UNION ALL SELECT 'movie_keyword', COUNT(*) FROM movie_keyword
UNION ALL SELECT 'name', COUNT(*) FROM name
UNION ALL SELECT 'person_info', COUNT(*) FROM person_info
UNION ALL SELECT 'role_type', COUNT(*) FROM role_type
UNION ALL SELECT 'title', COUNT(*) FROM title
ORDER BY table_name;
SQL


-- Flags: Scale Down False, Union False, OJ False, NEP False, CS2 False
-- Extraction Pipeline
-- seed_sample_size_per 0.32
-- Start from 11:08:20.480622
-- /Users/akshay/Documents/Semesters/Sem5/ADBMS/PRISM/mysite/unmasque/src/core/view_minimizer.py:132:UserWarning: pandas only supports SQLAlchemy connectable (engine/connection) or database string URI or sqlite3 DBAPI2 connection. Other DBAPI2 objects are not tested. Please consider using SQLAlchemy.
--   sql_query = pd.read_sql_query(self.connectionHelper.queries.get_star(tabname), self.connectionHelper.conn)
-- ============= Given Query ===============
-- SELECT chn.name AS voiced_char,
--        n.name AS voicing_actress,
--        t.title AS voiced_animation
-- FROM aka_name AS an,
--      complete_cast AS cc,
--      comp_cast_type AS cct,
--      char_name AS chn,
--      cast_info AS ci,
--      company_name AS cn,
--      info_type AS it,
--      keyword AS k,
--      movie_companies AS mc,
--      movie_info AS mi,
--      movie_keyword AS mk,
--      name AS n,
--      person_info AS pi,
--      role_type AS rt,
--      title AS t
-- WHERE cct.kind ='cast'
--   AND ci.note = '(voice)' 
--   AND cn.country_code ='[us]'
--   AND it.info = 'release dates'
--   AND k.keyword = 'computer-animation'
--   AND mi.info IS NOT NULL
--   AND mi.info LIKE 'USA:%200%'
--   AND n.gender ='f'
--   AND n.name LIKE '%An%'
--   AND rt.role ='actress'
--   AND t.production_year BETWEEN 2000 AND 2010
--   -- ----------------------------------------------------
--   -- Redundant Joins Block (12 Redundant Joins Retained)
--   -- ----------------------------------------------------
--   AND t.id = mi.movie_id
--   AND t.id = mc.movie_id
--   AND t.id = ci.movie_id
--   AND t.id = mk.movie_id
--   AND t.id = cc.movie_id
--   AND mc.movie_id = ci.movie_id
--   AND mc.movie_id = mi.movie_id
--   AND mc.movie_id = mk.movie_id
--   AND mc.movie_id = cc.movie_id
--   AND mi.movie_id = ci.movie_id
--   AND mi.movie_id = mk.movie_id
--   AND mi.movie_id = cc.movie_id
--   AND ci.movie_id = mk.movie_id
--   AND ci.movie_id = cc.movie_id
--   AND mk.movie_id = cc.movie_id
--   AND cn.id = mc.company_id
--   AND it.id = mi.info_type_id
--   AND n.id = ci.person_id
--   AND rt.id = ci.role_id
--   AND n.id = an.person_id
--   AND ci.person_id = an.person_id
--   AND chn.id = ci.person_role_id
--   AND n.id = pi.person_id
--   AND ci.person_id = pi.person_id
--   AND k.id = mk.keyword_id
--   AND cct.id = cc.subject_id;
    
-- =========== Extracted Query =============
 
--  Select char_name.name as voiced_char, name.name as voicing_actress, title.title as voiced_animation 
--  From aka_name, cast_info, char_name, comp_cast_type, company_name, complete_cast, info_type, keyword, movie_companies, movie_info, movie_keyword, name, person_info, role_type, title 
--  Where keyword.id = movie_keyword.keyword_id
--  and info_type.id = movie_info.info_type_id
--  and company_name.id = movie_companies.company_id
--  and comp_cast_type.id = complete_cast.subject_id
--  and cast_info.role_id = role_type.id
--  and cast_info.person_role_id = char_name.id
--  and aka_name.person_id = cast_info.person_id
--  and cast_info.person_id = name.id
--  and name.id = person_info.person_id
--  and cast_info.movie_id = complete_cast.movie_id
--  and complete_cast.movie_id = movie_companies.movie_id
--  and movie_companies.movie_id = movie_info.movie_id
--  and movie_info.movie_id = movie_keyword.movie_id
--  and movie_keyword.movie_id = title.id
--  and cast_info.note = '(voice)'
--  and comp_cast_type.kind = 'cast'
--  and company_name.country_code = '[us]'
--  and info_type.info = 'release dates'
--  and keyword.keyword = 'computer-animation'
--  and name.gender = 'f'
--  and role_type.role = 'actress'
--  and movie_info.info LIKE 'USA:%200%'
--  and name.name LIKE '%An%'
--  and title.production_year between 2000 and 2010;
-- ================ Profile ================
-- ╒══════════════════════╤════════════╤═════════╕
-- │ Step                 │   Time (s) │   Total │
-- ╞══════════════════════╪════════════╪═════════╡
-- │ From Clause:         │       0.27 │      21 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Union:               │       0    │       0 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Restore DB:          │       0.01 │       0 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Correlated Sampling: │       0    │       0 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ View Minimization:   │       0.64 │      16 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Where Clause:        │     490.32 │   18109 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Projection:          │       2.72 │     126 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Group BY:            │       3.68 │      81 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Aggregation:         │       0.04 │       0 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Order by:            │       0.32 │       6 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Limit:               │       6.96 │      15 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Outer Join:          │       0    │       0 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ NEP:                 │       0    │       0 │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Result               │       0.14 │       1 │
-- │  Comparator:         │            │         │
-- ├──────────────────────┼────────────┼─────────┤
-- │ Total:               │     505.32 │   18375 │
-- ╘══════════════════════╧════════════╧═════════╛