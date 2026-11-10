-- |AUX| = 25 tables, 3 subqueries, tables per subquery: [9, 8, 8]
(SELECT t01_key AS k, t01_name AS nm
 FROM t01, t02, t03, t04, t05, t06, t07, t08, t09
 WHERE t01_key = t02_key
   AND t02_key = t03_key
   AND t03_key = t04_key
   AND t04_key = t05_key
   AND t05_key = t06_key
   AND t06_key = t07_key
   AND t07_key = t08_key
   AND t08_key = t09_key
   AND t01_val < 40)
UNION ALL
(SELECT t10_key AS k, t10_name AS nm
 FROM t10, t11, t12, t13, t14, t15, t16, t17
 WHERE t10_key = t11_key
   AND t11_key = t12_key
   AND t12_key = t13_key
   AND t13_key = t14_key
   AND t14_key = t15_key
   AND t15_key = t16_key
   AND t16_key = t17_key
   AND t10_grp <= 2)
UNION ALL
(SELECT t18_key AS k, t18_name AS nm
 FROM t18, t19, t20, t21, t22, t23, t24, t25
 WHERE t18_key = t19_key
   AND t19_key = t20_key
   AND t20_key = t21_key
   AND t21_key = t22_key
   AND t22_key = t23_key
   AND t23_key = t24_key
   AND t24_key = t25_key
   AND t18_val > 60);
