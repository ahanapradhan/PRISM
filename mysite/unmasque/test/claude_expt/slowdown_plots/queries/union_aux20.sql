-- |AUX| = 20 tables, 3 subqueries, tables per subquery: [7, 7, 6]
(SELECT t01_key AS k, t01_name AS nm
 FROM t01, t02, t03, t04, t05, t06, t07
 WHERE t01_key = t02_key
   AND t02_key = t03_key
   AND t03_key = t04_key
   AND t04_key = t05_key
   AND t05_key = t06_key
   AND t06_key = t07_key
   AND t01_val < 40)
UNION ALL
(SELECT t08_key AS k, t08_name AS nm
 FROM t08, t09, t10, t11, t12, t13, t14
 WHERE t08_key = t09_key
   AND t09_key = t10_key
   AND t10_key = t11_key
   AND t11_key = t12_key
   AND t12_key = t13_key
   AND t13_key = t14_key
   AND t08_grp <= 2)
UNION ALL
(SELECT t15_key AS k, t15_name AS nm
 FROM t15, t16, t17, t18, t19, t20
 WHERE t15_key = t16_key
   AND t16_key = t17_key
   AND t17_key = t18_key
   AND t18_key = t19_key
   AND t19_key = t20_key
   AND t15_val > 60);
