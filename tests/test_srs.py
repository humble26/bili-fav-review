import unittest
from datetime import date

from bili_fav_review.store.srs import (
    GRADE_FORGOT,
    GRADE_FUZZY,
    GRADE_OK,
    apply_review,
    new_state,
)

TODAY = date(2026, 9, 13)


class TestSRS(unittest.TestCase):
    def test_new_state(self):
        st = new_state("2026-09-14")
        self.assertEqual(st["reps"], 0)
        self.assertEqual(st["due_date"], "2026-09-14")

    def test_first_ok_is_two_days(self):
        st = apply_review(new_state("2026-09-14"), GRADE_OK, TODAY)
        self.assertEqual(st["reps"], 1)
        self.assertEqual(st["interval_days"], 2.0)
        self.assertEqual(st["due_date"], "2026-09-15")

    def test_growth_compounds(self):
        st = new_state("2026-09-14")
        st = apply_review(st, GRADE_OK, TODAY)  # 2d, ease 2.35
        st = apply_review(st, GRADE_OK, TODAY)  # 2*2.35
        self.assertAlmostEqual(st["interval_days"], 4.7, places=1)
        st = apply_review(st, GRADE_OK, TODAY)  # 4.7*2.4
        self.assertAlmostEqual(st["interval_days"], 11.3, delta=0.15)

    def test_forgot_resets(self):
        st = new_state("2026-09-14")
        st = apply_review(st, GRADE_OK, TODAY)
        st = apply_review(st, GRADE_OK, TODAY)
        st = apply_review(st, GRADE_FORGOT, TODAY)
        self.assertEqual(st["reps"], 0)
        self.assertEqual(st["interval_days"], 1.0)
        self.assertEqual(st["lapses"], 1)
        self.assertEqual(st["due_date"], "2026-09-14")

    def test_fuzzy_shrinks_interval(self):
        st = new_state("2026-09-14")
        st = apply_review(st, GRADE_OK, TODAY)
        st = apply_review(st, GRADE_FUZZY, TODAY)
        self.assertEqual(st["interval_days"], 1.2)  # 2 * 0.6
        self.assertEqual(st["due_date"], "2026-09-14")

    def test_ease_bounds(self):
        st = new_state("2026-09-14")
        for _ in range(30):
            st = apply_review(st, GRADE_OK, TODAY)
        self.assertLessEqual(st["ease"], 3.0)
        for _ in range(60):
            st = apply_review(st, GRADE_FORGOT, TODAY)
        self.assertGreaterEqual(st["ease"], 1.3)

    def test_interval_capped(self):
        st = new_state("2026-09-14")
        for _ in range(60):
            st = apply_review(st, GRADE_OK, TODAY)
        self.assertLessEqual(st["interval_days"], 365.0)


if __name__ == "__main__":
    unittest.main()
