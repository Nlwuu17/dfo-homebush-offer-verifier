import copy
import unittest
from unittest.mock import patch

from dfo import replay, run, stop
from providers import Provider
from verify_offer import ROOT, NO, WAIT, YES, UNKNOWN, Reader, decide, inspect, load

DOC = load(ROOT / "data/dev/document.json")
CASE = dict(
    id="dev",
    brand="练习品牌",
    offer="Up to 30% off shoes",
    centre="DFO Homebush",
    day="2026-11-04",
    event="Weekend",
    split="dev",
    catalogue=[{k: DOC[k] for k in ("title", "type", "id")}],
)
POLICY = load(ROOT / "policy.json")


class OfflineChecks(unittest.TestCase):
    def result(self, doc=DOC, case=CASE, claims=None):
        if claims is None:
            claims = Provider().extract(case, doc)
        return inspect(case, doc, claims)

    def test_reader_guards(self):
        rows = [{"id": str(i)} for i in range(5)]
        reader = Reader(rows, {r["id"]: r for r in rows}, 3)
        for invalid in ("unknown", "0", "0", "1", "2", "3"):
            if invalid in ("unknown", "3") or invalid in reader.seen:
                with self.assertRaises(ValueError):
                    reader.read(invalid)
            else:
                reader.read(invalid)
        self.assertEqual(reader.seen, {"0", "1", "2"})

    def test_selector_rejection(self):
        with patch.object(Provider, "select", return_value=("unavailable", "bad id")):
            with self.assertRaises(ValueError):
                run(CASE, {DOC["id"]: DOC}, POLICY, "B", None, "dev")

    def test_citation_and_qualifier(self):
        claims = Provider().extract(CASE, DOC)
        term = next(c for c in claims if c["field"] == "offer")
        for quote, found in [("30% off shoes", True), ("All shoes 30% off", False)]:
            term["quote"] = quote
            case = dict(CASE, offer=quote)
            record = self.result(case=case, claims=claims)
            self.assertEqual(
                next(c["found"] for c in record["citations"] if c["field"] == "offer"),
                found,
            )
            self.assertEqual(decide([record])[0], UNKNOWN)

    def test_location_binding(self):
        claims = Provider().extract(CASE, DOC)
        claims[0]["location"] = "different paragraph"
        self.assertFalse(self.result(claims=claims)["citations"][0]["found"])

    def test_dates_scope_and_identity(self):
        self.assertEqual(decide([self.result()])[0], YES)
        for field, value in [
            ("day", "2026-11-09"),
            ("brand", "另一品牌"),
            ("offer", "Up to 20% off shoes"),
        ]:
            self.assertEqual(
                decide([self.result(case=dict(CASE, **{field: value}))])[0], UNKNOWN
            )
        for typ in ("other_centre", "social", "directory"):
            self.assertEqual(decide([self.result(dict(DOC, type=typ))])[0], UNKNOWN)
        for key, value in [("范围", "Outlet Stores Only"), ("日期", "dates to follow")]:
            doc = copy.deepcopy(DOC)
            doc["paragraphs"][key] = value
            self.assertEqual(decide([self.result(doc)])[0], WAIT)

    def test_conflict_persists(self):
        excluded = copy.deepcopy(DOC)
        excluded["paragraphs"]["范围"] = "Excluded store: DFO Homebush"
        no = self.result(excluded)
        self.assertEqual(decide([no])[0], NO)
        label, _ = decide([no, self.result()])
        self.assertEqual(label, WAIT)
        self.assertIsNone(stop(label, 2, 4, 3))
        self.assertEqual(stop(label, 3, 4, 3), "预算用尽")

    def test_replay_checks_quotes(self):
        docs = {DOC["id"]: DOC}
        t = run(CASE, docs, POLICY, "B", None, "dev")
        replay(t, CASE, docs, POLICY, "dev")
        t["steps"][0]["evidence"]["citations"][0]["quote"] = "tampered"
        with self.assertRaises(ValueError):
            replay(t, CASE, docs, POLICY, "dev")

    def test_contract_separation(self):
        class Probe(Provider):
            def request(inner, role, prompt, payload, fixture):
                if role == "select":
                    self.assertEqual(set(payload["unread"][0]), {"id", "title", "type"})
                    self.assertEqual(payload["evidence"], [])
                self.assertFalse(
                    set(payload["offer"])
                    & {"gold", "label", "id", "split", "catalogue"}
                )
                return super(Probe, inner).request(role, prompt, payload, fixture)

        with patch("dfo.Provider", Probe):
            run(CASE, {DOC["id"]: DOC}, POLICY, "B", None, "dev")
