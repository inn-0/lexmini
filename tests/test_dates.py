# tests/test_dates.py
"""Regression checks for missed legal dates and false date-shaped numbers."""
import unittest

from lexmini.dates import date_spans


class DateTests(unittest.TestCase):
  def test_multilingual_and_broken_lines(self):
    values = ["21 février 2008", "29 octobre \n2019", "7. November 2022", "1º gennaio 2021",
      "November 7, 2022", "3 octobre suivant", "7 n o v e m b r e 2 0 2 2", "2022-11-07", "07/11/2022"]
    for value in values:
      with self.subTest(value=value):
        spans = date_spans(value)
        self.assertEqual(len(spans), 1)
        expected = "3 octobre" if value.endswith("suivant") else value
        self.assertEqual(value[spans[0]["start"]:spans[0]["end"]], expected)

  def test_invalid_dates_and_month_year_do_not_become_days(self):
    for value in ["31 février 2022", "31.02.2022", "2022-13-07", "novembre 2022", "art. 12.3.4", "E-1088/2022"]:
      with self.subTest(value=value):
        self.assertEqual(date_spans(value), [])

  def test_omitted_year_and_leap_day(self):
    self.assertEqual(len(date_spans("29 février")), 1)
    self.assertEqual(date_spans("29 février 2021"), [])
    self.assertEqual(len(date_spans("29 février 2020")), 1)
