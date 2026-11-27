"""The shared stop policy for arms A and B, on synthetic sources only.

After the first definite verdict, at most one check read of a source that may
state the same offer, if the budget allows; then the judge decides again on
everything read. No candidate case's verdict is asserted here.
"""

import unittest

import bf26

BASE = {
    "brand": "Testbrand",
    "offer": "全店 30% off",
    "as_of_date": "2026-11-26",
    "timezone": "Australia/Sydney",
    "centre": "DFO Homebush",
}


def page(key, start, end):
    return {
        "id": key,
        "title": "Testbrand | 30% Off Storewide - DFO Homebush",
        "publisher": "DFO Homebush",
        "source_type": "商场品牌优惠页",
        "url": "https://example.test/" + key,
        "checked_date": "2026-11-26",
        "passages": [{"summary_zh": f"{start} 至 {end}：全店 30% off。"}],
    }


def flyer(key, text):
    return {
        "id": key,
        "title": "DFO Homebush The Big Shopping Week 2026 活动传单",
        "publisher": "DFO Homebush",
        "source_type": "商场活动传单",
        "url": "https://example.test/" + key,
        "checked_date": "2026-11-26",
        "passages": [{"locator": "第 1 页 / Testbrand", "summary_zh": text}],
    }


def store(key):
    return {
        "id": key,
        "title": "Testbrand - DFO Homebush",
        "publisher": "DFO Homebush",
        "source_type": "商场门店页",
        "url": "https://example.test/" + key,
        "checked_date": "2026-11-26",
        "passages": [{"summary_zh": "门店页列出 Testbrand 位于 DFO Homebush。"}],
    }


def case_of(*docs):
    case = dict(
        BASE,
        case_id="T",
        question="测试",
        catalogue=[{k: d[k] for k in ("id", "title", "source_type")} for d in docs],
    )
    return case, {d["id"]: d for d in docs}


def path(trace):
    return [s["source_id"] for s in trace["steps"]]


class SharedStopTests(unittest.TestCase):
    def test_agreeing_check_read_ends_with_check_done(self):
        case, docs = case_of(
            page("P1", "2026-11-26", "2026-11-29"),
            flyer("F1", "全店 30% off，有效期 11/13–11/30。"),
            store("S1"),
        )
        for arm in "AB":
            t = bf26.run(case, docs, arm)
            self.assertEqual((t["label"], t["stop_reason"]), (bf26.YES, "补查完成"), arm)
            self.assertEqual(path(t), ["P1", "F1"], arm)
            self.assertTrue(t["steps"][1]["selection_reason"].startswith("补查同一优惠："))

    def test_conflicting_check_read_becomes_f(self):
        case, docs = case_of(
            page("P1", "2026-11-26", "2026-11-29"),
            flyer("F1", "全店 30% off，有效期 11/20–11/25。"),
        )
        t = bf26.run(case, docs, "B")
        self.assertEqual(t["label"], bf26.UNKNOWN)
        self.assertEqual(t["steps"][-1]["citations"], ["P1", "F1"])
        self.assertEqual(t["stop_reason"], "目录已读完")

    def test_rule_a_on_the_first_read_is_checked_too(self):
        case, docs = case_of(
            flyer("F1", "全店 30% off，有效期 11/20–11/25。"),
            page("P1", "2026-11-26", "2026-11-29"),
        )
        # Arm A reads the offer page first; arm B too. Either way the second
        # read reveals the conflict, so the order cannot decide the answer.
        for arm in "AB":
            self.assertEqual(bf26.run(case, docs, arm)["label"], bf26.UNKNOWN, arm)

    def test_no_relevant_candidate_left(self):
        case, docs = case_of(page("P1", "2026-11-26", "2026-11-29"), store("S1"))
        t = bf26.run(case, docs, "A")
        self.assertEqual((t["label"], t["stop_reason"]), (bf26.YES, "没有相关候选"))
        self.assertEqual(path(t), ["P1"])

    def test_budget_used_up_at_the_verdict(self):
        case, docs = case_of(page("P1", "2026-11-26", "2026-11-29"), flyer("F1", "无关。"))
        t = bf26.run(case, docs, "A", budget=1)
        self.assertEqual((t["label"], t["stop_reason"]), (bf26.YES, "预算用尽"))

    def test_first_verdict_policy_is_the_old_behaviour(self):
        case, docs = case_of(
            page("P1", "2026-11-26", "2026-11-29"),
            flyer("F1", "全店 30% off，有效期 11/20–11/25。"),
        )
        t = bf26.run(case, docs, "A", policy="first_verdict")
        self.assertEqual((t["label"], t["stop_reason"], path(t)), (bf26.YES, "证据充分", ["P1"]))
        with self.assertRaises(ValueError):
            bf26.run(case, docs, "A", policy="never")


class RelevanceTests(unittest.TestCase):
    def test_metadata_only(self):
        rows = [
            {"id": "a", "title": "Testbrand | Offer", "source_type": "商场品牌优惠页"},
            {"id": "b", "title": "Otherbrand | Offer", "source_type": "商场品牌优惠页"},
            {"id": "c", "title": "Any flyer", "source_type": "商场活动传单"},
            {"id": "d", "title": "Testbrand - DFO Homebush", "source_type": "商场门店页"},
            {"id": "e", "title": "Event", "source_type": "商场活动页"},
            {"id": "f", "title": "Testbrand terms", "source_type": "品牌活动条款"},
            {"id": "g", "title": "Testbrand stores", "source_type": "品牌门店目录"},
        ]
        self.assertEqual([r["id"] for r in bf26.relevant(BASE, rows)], ["a", "c", "f"])

    def test_stop_after_table(self):
        s = bf26.stop_after
        Y, U = bf26.YES, bf26.UNKNOWN
        self.assertEqual(s(Y, 1, 3, 3, ["x"], False, "confirm"), (None, True))
        self.assertEqual(s(Y, 2, 3, 3, ["x"], True, "confirm"), ("补查完成", True))
        self.assertEqual(s(Y, 3, 4, 3, ["x"], False, "confirm"), ("预算用尽", False))
        self.assertEqual(s(Y, 1, 3, 3, [], False, "confirm"), ("没有相关候选", False))
        self.assertEqual(s(U, 2, 3, 3, ["x"], True, "confirm"), (None, True))
        self.assertEqual(s(U, 3, 3, 3, [], True, "confirm"), ("目录已读完", True))
        self.assertEqual(s(Y, 1, 3, 3, ["x"], False, "first_verdict"), ("证据充分", False))


if __name__ == "__main__":
    unittest.main()
