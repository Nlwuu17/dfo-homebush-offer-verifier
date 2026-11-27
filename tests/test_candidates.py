"""Loading, splitting and scoring the candidate case set.

These tests check the plumbing only. They never assert a strategy's verdict
on a candidate case, so they cannot leak or bake in expected labels.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import bf26
from verify_offer import ROOT

CANDIDATES = ROOT / "data/candidates_2026_11_26"


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.cases, self.docs = bf26.inputs(CANDIDATES)

    def test_inputs_accept_centre_store_pages(self):
        self.assertEqual(len(self.cases), 20)
        kinds = {d["source_type"] for d in self.docs.values()}
        self.assertIn("商场门店页", kinds)
        self.assertLess(bf26.ORDER.index("品牌门店目录"), bf26.ORDER.index("商场门店页"))

    def test_store_page_alone_is_not_an_offer(self):
        case = self.cases["NC13"]
        page = self.docs["N11"]
        label, _, refs, _ = bf26.assess(case, [page])
        self.assertEqual(label, bf26.UNKNOWN)
        self.assertEqual(refs, ["N11"])

    def test_split_selection(self):
        dev = bf26.select(CANDIDATES, self.cases, "dev")
        held = bf26.select(CANDIDATES, self.cases, "heldout")
        both = bf26.select(CANDIDATES, self.cases, "all")
        self.assertEqual((len(dev), len(held), len(both)), (15, 5, 20))
        self.assertFalse(dev.keys() & held.keys())
        with self.assertRaises(ValueError):
            bf26.select(CANDIDATES, self.cases, "test")

    def test_folders_without_splits_have_no_heldout(self):
        cases, _ = bf26.inputs(bf26.DATA)
        self.assertEqual(bf26.select(bf26.DATA, cases, "dev"), cases)
        self.assertEqual(bf26.select(bf26.DATA, cases, "heldout"), {})

    def test_splits_are_fixed_by_case_id_hash(self):
        import hashlib

        splits = json.loads((CANDIDATES / "splits.json").read_text("utf-8"))
        for key, split in splits.items():
            digest = int(hashlib.sha256(key.encode()).hexdigest(), 16)
            self.assertEqual(split, "heldout" if digest % 3 == 0 else "dev", key)

    def test_unlabelled_cases_are_reported_not_scored(self):
        # Work on a copy with every label cleared, so the real labels are
        # untouched, and never print the table on failure: it holds
        # strategy verdicts on the dev split.
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "c"
            shutil.copytree(CANDIDATES, folder)
            labels = json.loads((folder / "labels_todo.json").read_text("utf-8"))
            for row in labels:
                row.update(label=None, reason="", supporting_evidence_ids=[])
            (folder / "labels_todo.json").write_text(json.dumps(labels), "utf-8")
            cases = bf26.select(folder, self.cases, "dev")
            traces = [bf26.run(c, self.docs, arm) for c in cases.values() for arm in "AB"]
            scored = bf26.score(folder, cases, traces, "labels_todo.json")
            table = bf26.report(cases, scored, "t")
        self.assertTrue("| A | 0/0 |" in table, "A 组应为 0/0")
        self.assertTrue("另有 15/15 个案例未标注" in table, "应提示 15 个未标注")
        self.assertFalse("| 是 |" in table, "未标注案例不应计分")

    def test_frozen_labels_are_complete_and_checksummed(self):
        import hashlib

        labels = json.loads((CANDIDATES / "labels_todo.json").read_text("utf-8"))
        self.assertEqual([r["case_id"] for r in labels], list(self.cases))
        self.assertTrue(all(r["label"] in (bf26.YES, bf26.NO, bf26.UNKNOWN) for r in labels))
        sums = dict(
            reversed(line.split()) for line in
            (CANDIDATES / "SHA256SUMS").read_text("utf-8").splitlines()
        )
        digest = hashlib.sha256((CANDIDATES / "labels_todo.json").read_bytes()).hexdigest()
        self.assertEqual(sums["labels_todo.json"], digest)

    def test_label_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "c"
            shutil.copytree(CANDIDATES, folder)
            labels = json.loads((folder / "labels_todo.json").read_text("utf-8"))
            cases = bf26.select(folder, self.cases, "dev")
            traces = [bf26.run(cases["NC01"], self.docs, "A")]
            one = {"NC01": cases["NC01"]}

            labels[0].update(label="适用", supporting_evidence_ids=["N03"])
            (folder / "labels_todo.json").write_text(json.dumps(labels), "utf-8")
            scored = bf26.score(folder, one, traces, "labels_todo.json")
            self.assertEqual(scored["NC01", "A"][1], "适用")

            for bad in ({"label": "maybe"}, {"supporting_evidence_ids": ["N99"]},
                        {"supporting_evidence_ids": []}):
                broken = [dict(labels[0], **bad)] + labels[1:]
                (folder / "labels_todo.json").write_text(json.dumps(broken), "utf-8")
                with self.assertRaises(ValueError):
                    bf26.score(folder, one, traces, "labels_todo.json")


if __name__ == "__main__":
    unittest.main()
