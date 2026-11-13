import io
import unittest
from contextlib import redirect_stdout

from mysite.unmasque.src.core.elapsed_time import create_zero_time_profile


class ElapsedTimeTest(unittest.TestCase):

    def test_init_time_is_separate_from_module_rows(self):
        profile = create_zero_time_profile()
        profile.update_for_init(102.31, 7)
        profile.update_for_from_clause(0.11, 8)

        self.assertAlmostEqual(profile.t_init, 102.31)
        self.assertAlmostEqual(profile.t_from_clause, 0.11)
        self.assertEqual(profile.app_init, 7)
        # Init is reported separately, so it must not appear in the table rows.
        self.assertNotIn(102.31, profile.get_times())

    def test_update_merges_every_module_and_accumulates_app_total(self):
        main = create_zero_time_profile()
        main.update_for_app(10)
        main.update_for_from_clause(1.0, 2)

        sub = create_zero_time_profile()
        sub.update_for_init(6.0, 7)
        sub.update_for_view_minimization(2.0, 3)
        sub.update_for_where_clause(3.0, 4)
        sub.update_for_outer_join(4.0, 5)
        sub.update_for_result_comparator(5.0, 6)
        sub.update_for_app(2)

        main.update(sub)

        self.assertAlmostEqual(main.t_from_clause, 1.0)
        self.assertAlmostEqual(main.t_init, 6.0)
        self.assertAlmostEqual(main.t_view_min, 2.0)
        self.assertAlmostEqual(main.t_where_clause, 3.0)
        self.assertAlmostEqual(main.t_outer_join, 4.0)
        self.assertAlmostEqual(main.t_result_comp, 5.0)
        # update() must add app counts rather than overwrite the total.
        self.assertEqual(main.app_init, 7)
        self.assertEqual(main.app_total, 12)

    def test_print_reports_two_totals(self):
        profile = create_zero_time_profile()
        profile.update_for_init(102.31, 7)
        profile.update_for_from_clause(0.11, 8)
        profile.update_for_app(328)
        profile.update_for_total_time(106.1)

        out = io.StringIO()
        with redirect_stdout(out):
            profile.print()

        output = out.getvalue()
        self.assertIn("Pre-extraction init/backup: 102.31 s", output)
        self.assertIn("PRISM-total:", output)
        self.assertIn("Wall-clock:", output)
        self.assertAlmostEqual(profile.get_prism_total(), 3.79)
        self.assertAlmostEqual(profile.get_wall_clock_total(), 106.1)
        # App calls for the wall-clock row include the pre-extraction work.
        self.assertIn(str(profile.app_total + profile.app_init), output)


if __name__ == "__main__":
    unittest.main()
