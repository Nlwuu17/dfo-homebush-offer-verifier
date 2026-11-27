import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from v03 import api, tracking
from v03.tracking import Entry, verify

URL = "https://www.homebush.dfo.com.au/offers/tommy-hilfiger-black-friday-november-2026-tommy-hilfiger"
FLYER = "https://a.storyblok.com/f/62361/x/6c883149fe/dfoh_the-big-shopping-week_flyer-2026.pdf"


def submit(**values):
    return Entry.model_validate(
        dict({"brand": "Tommy Hilfiger", "url": URL, "day": "2026-11-26"}, **values)
    )


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_recheck(self):
        entry = submit()
        first = await verify(entry, [])
        second = await verify(entry, [FLYER])
        self.assertEqual(first["citations"], ["TH-BF"])
        self.assertEqual([r["label"] for r in (first, second)], ["适用", "适用"])
        self.assertEqual([s["id"] for s in second["snapshots"]], ["TH-BF", "TH-FLYER"])
        self.assertEqual(second["snapshots"][1]["end"], "2026-11-30")
        self.assertEqual(second["citations"], ["TH-BF"])
        self.assertEqual(len(first["snapshots"]), 1)

    async def test_identity_scope_dates(self):
        for obj in [
            submit(text="指定款减 15%"),
            submit(brand="Coach"),
            submit(day="2027-01-01"),
            submit(url=URL.replace("homebush", "essendon")),
        ]:
            self.assertEqual((await verify(obj, []))["label"], "证据不足")
        entry = submit(url=None, text="全店按原价减 50%")
        self.assertEqual((await verify(entry, []))["label"], "适用")
        self.assertEqual(
            (await verify(submit(url=URL + "?utm_source=email"), []))["label"], "适用"
        )
        with self.assertRaises(ValueError):
            await verify(entry, ["https://example.org/not-registered"])

    async def test_two_same_brand_offers(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "library"
            shutil.copytree(tracking.HERE / "library", p)
            other = json.loads((p / "tommy.json").read_text())
            other.update(key="test-only-other", aliases=["仅测试：全店减 60%"])
            s = other["sources"][0]
            s.update(
                id="TEST-60",
                url="https://example.org/fixture",
                terms="测试资料",
                test_only=True,
            )
            (p / "other.json").write_text(json.dumps(other))
            with patch.dict(os.environ, {"DFO_CATALOGUE_DIR": folder}):
                r = await verify(submit(), [])
                self.assertEqual(r["citations"], ["TH-BF"])
                self.assertEqual(
                    (await verify(submit(text=other["aliases"][0]), []))["label"],
                    "证据不足",
                )

    async def test_synthetic_exclusion_changes_conclusion(self):
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree(tracking.HERE / "library", Path(folder) / "library")
            p = Path(folder) / "supplements"
            p.mkdir()
            fixture = json.loads(
                (tracking.HERE / "supplements/tommy-flyer.json").read_text()
            )
            s = fixture["sources"][0]
            s.update(
                id="TEST-EXCLUSION",
                scope="homebush_excluded",
                scope_text="仅测试：排除本店",
                test_only=True,
                url="https://example.org/test-exclusion",
                quote="Synthetic exclusion",
                terms="测试资料",
            )
            (p / "test.json").write_text(json.dumps(fixture))
            with patch.dict(os.environ, {"DFO_CATALOGUE_DIR": folder}):
                before = await verify(submit(), [])
                after = await verify(submit(), [s["url"]])
            self.assertEqual((before["label"], after["label"]), ("适用", "证据不足"))
            self.assertIn("冲突", after["reason"])
            self.assertTrue(after["snapshots"][1]["test_only"])

    async def test_frozen_cases_and_llm_adapter(self):
        cases, _ = tracking.bf26.inputs(tracking.bf26.DATA)
        for c in cases.values():
            e = submit(brand=c["brand"], text=c["offer"], url=None)
            r = await verify(e, [])
            self.assertEqual(
                r["label"],
                {"BF26-01": "适用", "BF26-02": "不适用", "BF26-03": "证据不足"}[
                    c["case_id"]
                ],
            )
        original = tracking.agent.llm

        async def mock_tool(*a):
            return dict(
                model="mock",
                tools=[
                    dict(
                        name="read_evidence",
                        arguments='{"evidence_id":"TH-BF","reason":"核对门店条款"}',
                    )
                ],
            )

        async def simulated(*args, **kwargs):
            return await original(*args, invoke=mock_tool, **kwargs)

        with (
            patch.object(tracking.agent, "configuration", return_value=("mock", None)),
            patch.object(tracking.agent, "llm", simulated),
        ):
            r = await verify(submit(mode="llm"), [])
        self.assertEqual(r["label"], "适用")
        self.assertEqual(len(r["calls"]), 1)


@unittest.skipUnless(os.getenv("DATABASE_URL"), "需要真实 PostgreSQL 连接")
class PgFlow(unittest.TestCase):
    def test_saved_history_across_api_lifespans(self):
        with TestClient(api.app) as c:
            response = c.post("/api/records", json=submit().model_dump(mode="json"))
            self.assertEqual(response.status_code, 201, response.text)
            path = "/api/records/" + response.json()["id"]
            v1 = c.get(path).json()["versions"][0]
        with TestClient(api.app) as c:
            self.assertEqual(c.get(path).json()["versions"], [v1])
            r = c.post(
                path + "/recheck", json={"expected_version": 1, "evidence_url": FLYER}
            )
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["versions"][0], v1)
            self.assertEqual(len(r.json()["versions"][1]["result"]["snapshots"]), 2)
            self.assertEqual(
                c.post(path + "/recheck", json={"expected_version": 1}).status_code, 409
            )
            self.assertEqual(
                c.post(
                    "/api/records", json=submit(text="减 80%").model_dump(mode="json")
                ).status_code,
                201,
            )
