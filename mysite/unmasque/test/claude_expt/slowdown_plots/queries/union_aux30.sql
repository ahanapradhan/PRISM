-- |AUX| = 30 tables, 3 subqueries, tables per subquery: [10, 10, 10]
(SELECT t01_key AS k, t01_name AS nm
 FROM t01, t02, t03, t04, t05, t06, t07, t08, t09, t10
 WHERE t01_key = t02_key
   AND t02_key = t03_key
   AND t03_key = t04_key
   AND t04_key = t05_key
   AND t05_key = t06_key
   AND t06_key = t07_key
   AND t07_key = t08_key
   AND t08_key = t09_key
   AND t09_key = t10_key
   AND t01_val < 40)
UNION ALL
(SELECT t11_key AS k, t11_name AS nm
 FROM t11, t12, t13, t14, t15, t16, t17, t18, t19, t20
 WHERE t11_key = t12_key
   AND t12_key = t13_key
   AND t13_key = t14_key
   AND t14_key = t15_key
   AND t15_key = t16_key
   AND t16_key = t17_key
   AND t17_key = t18_key
   AND t18_key = t19_key
   AND t19_key = t20_key
   AND t11_grp <= 2)
UNION ALL
(SELECT t21_key AS k, t21_name AS nm
 FROM t21, t22, t23, t24, t25, t26, t27, t28, t29, t30
 WHERE t21_key = t22_key
   AND t22_key = t23_key
   AND t23_key = t24_key
   AND t24_key = t25_key
   AND t25_key = t26_key
   AND t26_key = t27_key
   AND t27_key = t28_key
   AND t28_key = t29_key
   AND t29_key = t30_key
   AND t21_val > 60);
