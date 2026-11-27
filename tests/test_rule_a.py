"""Rule A (explicit periods that exclude the as-of date) and its boundary with F.

Synthetic cases and sources only, so no candidate case's verdict, dev or
held out, is asserted here.
"""

import unittest
from datetime import date

import bf26

CASE = {
    "case_id": "T01",
    "brand": "Testbrand",
    "offer": "全店 30% off",
    "as_of_date": "2026-11-26",
    "timezone": "Australia/Sydney",
    "centre": "DFO Homebush",
}


def page(start, end, key="P1"):
    return {
        "id": key,
        "title": "Testbrand | 30% Off Storewide - DFO Homebush",
        "publisher": "DFO Homebush",
        "source_type": "商场品牌优惠页",
        "checked_date": "2026-11-26",
        "passages": [{"summary_zh": f"{start} 至 {end}：全店 30% off。门店为 DFO Homebush 的 Testbrand。"}],
    }


def flyer(text, key="F1"):
    return {
        "id": key,
        "title": "DFO Homebush The Big Shopping Week 2026 活动传单",
        "publisher": "DFO Homebush",
        "source_type": "商场活动传单",
        "checked_date": "2026-11-26",
        "passages": [{"locator": "第 1 页 / Testbrand", "summary_zh": text}],
    }


def judge(*docs):
    label, _, refs, gap = bf26.assess(CASE, list(docs))
    return label, refs, gap


class BoundaryTests(unittest.TestCase):
    def test_every_explicit_period_excludes_the_date_is_rule_a(self):
        label, refs, _ = judge(
            page("2026-11-20", "2026-11-25"), flyer("全店 30% off，有效期 11/20–11/25。")
        )
        self.assertEqual(label, bf26.NO)
        self.assertEqual(refs, ["P1", "F1"])

    def test_different_periods_that_all_include_the_date_go_on(self):
        label, refs, _ = judge(
            page("2026-11-26", "2026-11-29"), flyer("全店 30% off，有效期 11/13–11/30。")
        )
        self.assertEqual(label, bf26.YES)
        self.assertEqual(refs, ["P1", "F1"])

    def test_one_period_includes_and_one_excludes_is_rule_f(self):
        label, refs, gap = judge(
            page("2026-11-26", "2026-11-29"), flyer("全店 30% off，有效期 11/20–11/25。")
        )
        self.assertEqual((label, gap), (bf26.UNKNOWN, "conflict"))
        self.assertEqual(refs, ["P1", "F1"])

    def test_order_of_reading_does_not_change_the_f_outcome(self):
        label, _, gap = judge(
            flyer("全店 30% off，有效期 11/20–11/25。"), page("2026-11-26", "2026-11-29")
        )
        self.assertEqual((label, gap), (bf26.UNKNOWN, "conflict"))

    def test_single_day_offer_on_another_day_is_rule_a(self):
        doc = page("2026-11-27", "2026-11-27")
        doc["passages"][0]["summary_zh"] = "仅限 2026-11-27 一天：全店 30% off。"
        self.assertEqual(judge(doc)[0], bf26.NO)

    def test_a_different_offer_out_of_window_does_not_trigger_a(self):
        label, refs, _ = judge(flyer("全店 25% off，有效期 11/16–11/24。"))
        self.assertEqual(label, bf26.UNKNOWN)
        self.assertNotIn("F1", refs)

    def test_missing_or_malformed_periods_are_not_explicit(self):
        for text in ("全店 30% off，未印有效期。", "全店 30% off，有效期印为 11/16–10/27。"):
            self.assertEqual(judge(flyer(text))[0], bf26.UNKNOWN, text)
        # A malformed flyer period neither excludes nor conflicts with a valid page.
        label, refs, _ = judge(
            page("2026-11-26", "2026-11-29"), flyer("全店 30% off，有效期印为 11/16–10/27。")
        )
        self.assertEqual((label, refs), (bf26.YES, ["P1"]))

    def test_another_brands_expired_flyer_entry_is_ignored(self):
        other = flyer("全店 30% off，有效期 11/20–11/25。")
        other["passages"][0]["locator"] = "第 1 页 / Otherbrand"
        self.assertEqual(judge(page("2026-11-26", "2026-11-29"), other)[0], bf26.YES)


class PeriodParsingTests(unittest.TestCase):
    def test_formats(self):
        doc = flyer("")
        self.assertEqual(
            bf26.period("有效期 11/16–11/24。", CASE, doc),
            (date(2026, 11, 16), date(2026, 11, 24)),
        )
        self.assertEqual(
            bf26.period("2026-11-26 至 2026-11-29：", CASE, doc),
            (date(2026, 11, 26), date(2026, 11, 29)),
        )
        self.assertEqual(
            bf26.period("仅限 2026-11-27 一天", CASE, doc), (date(2026, 11, 27),) * 2
        )
        self.assertIsNone(bf26.period("有效期印为 11/16–10/27", CASE, doc))
        self.assertIsNone(bf26.period("未印有效期", CASE, doc))

    def test_month_day_needs_a_year_in_the_title(self):
        doc = dict(flyer(""), title="活动传单")
        self.assertIsNone(bf26.period("有效期 11/16–11/24。", CASE, doc))

    def test_current_is_three_valued(self):
        doc = flyer("")
        self.assertIs(bf26.current("有效期 11/20–11/30。", CASE, doc), True)
        self.assertIs(bf26.current("有效期 11/20–11/25。", CASE, doc), False)
        self.assertIsNone(bf26.current("未印有效期", CASE, doc))


if __name__ == "__main__":
    unittest.main()
