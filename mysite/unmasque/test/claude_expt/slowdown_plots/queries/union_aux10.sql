-- |AUX| = 10 tables, 3 subqueries, tables per subquery: [4, 3, 3]
(SELECT t01_key AS k, t01_name AS nm
 FROM t01, t02, t03, t04
 WHERE t01_key = t02_key
   AND t02_key = t03_key
   AND t03_key = t04_key
   AND t01_val < 40)
UNION ALL
(SELECT t05_key AS k, t05_name AS nm
 FROM t05, t06, t07
 WHERE t05_key = t06_key
   AND t06_key = t07_key
   AND t05_grp <= 2)
UNION ALL
(SELECT t08_key AS k, t08_name AS nm
 FROM t08, t09, t10
 WHERE t08_key = t09_key
   AND t09_key = t10_key
   AND t08_val > 60);
