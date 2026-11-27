import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import bf26 as app


class RealEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.cases, self.docs = app.inputs(app.DATA)

    def test_budgets_and_citations_at_each_step(self):
        for case in self.cases.values():
            for arm in ("A", "B"):
                for budget in (1, 2, 3):
                    row = app.run(case, self.docs, arm, budget)
                    seen = set()
                    for step in row["steps"]:
                        self.assertNotIn(step["source_id"], seen)
                        seen.add(step["source_id"])
                        self.assertLessEqual(set(step["citations"]), seen)
                    self.assertEqual(row["query_count"], len(seen))
                    self.assertLessEqual(len(seen), budget)
                    self.assertLessEqual(set(row["citations"]), seen)
        with self.assertRaises(ValueError):
            app.run(next(iter(self.cases.values())), self.docs, "B", 4)

    def test_gold_only_accessed_by_scorer(self):
        with patch.object(app, "load", wraps=app.load) as read:
            cases, docs = app.inputs(app.DATA)
            rows = [app.run(c, docs, arm) for c in cases.values() for arm in ("A", "B")]
            self.assertEqual(
                [x.args[0].name for x in read.call_args_list],
                ["cases.json", "sources.json"],
            )
            app.score(app.DATA, cases, rows)
            self.assertEqual(read.call_args.args[0].name, "gold_labels.json")

    def test_comma_following_discount(self):
        self.assertEqual(
            app.tiers("指定商品减 20%，有除外项目。"), {"20%": {"指定", "除外"}}
        )
        self.assertNotIn("除外", app.tiers("减 20%；其他商品有除外项目。")["20%"])

    def test_membership_and_price_basis_need_both_documents(self):
        case = self.cases["BF26-01"]
        terms, flyer = (self.docs[k] for k in ("E02", "E07"))
        for doc in [terms, flyer]:
            self.assertEqual(app.assess(case, [doc])[0], app.UNKNOWN)
        self.assertEqual(app.assess(case, [terms, flyer])[0], app.YES)
        altered = copy.deepcopy(flyer)
        for passage in altered["passages"]:
            passage["summary_zh"] = passage["summary_zh"].replace("会员", "一般")
        self.assertEqual(app.assess(case, [terms, altered])[0], app.UNKNOWN)

    def test_changed_ids_do_not_change_results(self):
        for case in self.cases.values():
            remap = {k: f"other{i}" for i, k in enumerate(reversed(self.docs))}
            renamed = copy.deepcopy(case)
            for r in renamed["catalogue"]:
                r["id"] = remap[r["id"]]
            docs = {remap[k]: dict(v, id=remap[k]) for k, v in self.docs.items()}
            for arm in ("A", "B"):
                first = app.run(case, self.docs, arm)
                second = app.run(renamed, docs, arm)
                self.assertEqual(first["label"], second["label"])
                self.assertEqual(
                    [remap[s["source_id"]] for s in first["steps"]],
                    [s["source_id"] for s in second["steps"]],
                )

    def test_cross_references_rejected(self):
        bad = copy.deepcopy(list(self.cases.values()))
        bad[0]["catalogue"][0]["id"] = "missing"
        with patch.object(app, "load", side_effect=[bad, list(self.docs.values())]):
            with self.assertRaisesRegex(ValueError, "missing"):
                app.inputs(Path("."))
        gold = app.load(app.DATA / "gold_labels.json")
        gold[0]["supporting_evidence_ids"] = ["missing"]
        with patch.object(app, "load", return_value=gold):
            with self.assertRaisesRegex(ValueError, "BF26-01"):
                app.score(app.DATA, self.cases, [])
