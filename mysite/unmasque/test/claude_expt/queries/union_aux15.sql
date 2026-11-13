-- |AUX| = 15 tables, 3 subqueries, tables per subquery: [5, 5, 5]
(SELECT t01_key AS k, t01_name AS nm
 FROM t01, t02, t03, t04, t05
 WHERE t01_key = t02_key
   AND t02_key = t03_key
   AND t03_key = t04_key
   AND t04_key = t05_key
   AND t01_val < 40)
UNION ALL
(SELECT t06_key AS k, t06_name AS nm
 FROM t06, t07, t08, t09, t10
 WHERE t06_key = t07_key
   AND t07_key = t08_key
   AND t08_key = t09_key
   AND t09_key = t10_key
   AND t06_grp <= 2)
UNION ALL
(SELECT t11_key AS k, t11_name AS nm
 FROM t11, t12, t13, t14, t15
 WHERE t11_key = t12_key
   AND t12_key = t13_key
   AND t13_key = t14_key
   AND t14_key = t15_key
   AND t11_val > 60);
