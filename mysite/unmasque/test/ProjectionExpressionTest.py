import unittest

import numpy as np
from sympy import symbols

from mysite.unmasque.src.core.projection import (
    _cap_probe_last_digit,
    _random_numeric_probe,
    _snap_and_refit_constant,
    _solve_exact_linear_system,
    _stored_numeric_probe,
    beautify_scalar_func,
    round_expr,
)


class ProjectionExpressionTest(unittest.TestCase):
    def test_probe_last_digit_never_exceeds_four(self):
        for requested, expected in [
            (942.835, 942.834),
            (942.839, 942.834),
            (697.408, 697.404),
            (697.404, 697.404),
            (-942.839, -942.834),
        ]:
            self.assertAlmostEqual(_cap_probe_last_digit(requested), expected, places=6)

    def test_random_numeric_probe_uses_capped_last_digit(self):
        self.assertAlmostEqual(_random_numeric_probe(942.835, 942.835), 942.834, places=6)

    def test_stored_numeric_probe_matches_column_scale(self):
        self.assertAlmostEqual(_stored_numeric_probe(942.834), 942.83, places=6)
        self.assertAlmostEqual(_stored_numeric_probe(697.404), 697.40, places=6)
        self.assertAlmostEqual(_stored_numeric_probe(942.835), 942.84, places=6)

    def test_stored_coefficients_keep_mq10_run8_expression(self):
        # Reproduce the capped-probe MQ10 run whose coefficient matrix used
        # raw three-decimal values while the observed b used stored two-decimal
        # values. Solving against the stored values must recover [0, 1, -1, 0].
        raw_pairs = [
            (0.02, 40614.08, 39801.7984),
            (46.604, 106.411, -4852.296),
            (609.951, 830.530, -505751.2435),
            (424.464, 735.164, -311310.8536),
        ]
        coeff = []
        b = []
        for discount, price, observed in raw_pairs:
            stored_discount = _stored_numeric_probe(discount)
            stored_price = _stored_numeric_probe(price)
            coeff.append([
                stored_discount,
                stored_price,
                stored_discount * stored_price,
                1.0,
            ])
            b.append([observed])

        coeff = np.array(coeff)
        b = np.array(b)
        solution = _solve_exact_linear_system(coeff, b)
        solution = _snap_and_refit_constant(np.around(solution.copy(), 3), coeff, b, 2)

        self.assertEqual([round(float(v), 2) for v in solution.ravel()], [0.0, 1.0, -1.0, 0.0])

    def test_round_expr_keeps_factored_product_terms(self):
        l_discount, l_extendedprice = symbols('l_discount l_extendedprice')
        local_symbols = (l_discount, l_extendedprice, l_discount * l_extendedprice)
        solution = [-0.191, 1.0, -1.0, 33.51]
        expr = sum(value * coeff for value, coeff in zip(local_symbols, solution)) + solution[-1]

        rendered = str(round_expr(
            beautify_scalar_func(
                expr,
                local_symbols,
                [('lineitem', 'l_discount'), ('lineitem', 'l_extendedprice')],
            ),
            2,
        ))

        self.assertIn('l_discount', rendered)
        self.assertIn('l_extendedprice', rendered)
        self.assertIn('0.19*l_discount', rendered)
        self.assertNotEqual(rendered, 'l_extendedprice + 33.51')

    def test_noisy_residuals_do_not_invent_a_constant(self):
        coeff = np.array([
            [0.050, 46826.120, 2341.306, 1.0],
            [620.583, 311.334, 193208.588, 1.0],
            [753.338, 327.790, 246936.663, 1.0],
            [604.510, 495.570, 299577.021, 1.0],
        ])
        b = np.array([
            [44484.814],
            [-192893.841],
            [-246609.529],
            [-299081.451],
        ])
        solution = np.array([[0.0], [1.0], [-1.0], [0.69]])

        result = _snap_and_refit_constant(solution, coeff, b, 2)

        self.assertEqual(float(result[-1][0]), 0.0)

    def test_consistent_residual_keeps_real_constant(self):
        coeff = np.array([
            [0.0, 1.0, 0.0, 1.0],
            [2.0, 0.0, 1.0, 1.0],
            [1.0, 1.0, 1.0, 1.0],
            [0.0, 0.0, 0.0, 1.0],
        ])
        # With coefficients [0, 1, -1] the probe rows predict [1, -1, 0, 0].
        # A real +2 constant makes the observed results [3, 1, 2, 2].
        b = np.array([[3.0], [1.0], [2.0], [2.0]])
        solution = np.array([[0.0], [1.0], [-1.0], [0.0]])

        result = _snap_and_refit_constant(solution, coeff, b, 2)

        self.assertEqual(float(result[-1][0]), 2.0)


if __name__ == '__main__':
    unittest.main()
