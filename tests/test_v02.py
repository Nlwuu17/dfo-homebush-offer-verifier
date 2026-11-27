import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from v02 import agent, api


def fake(*actions):
    pending = iter(actions)

    async def invoke(model, messages, timeout):
        action = next(pending)
        if isinstance(action, Exception):
            raise action
        tool, args = action
        return {
            "model": "mock/fixture",
            "tools": [{"name": tool, "arguments": json.dumps(args)}],
            "input_tokens": 10,
            "output_tokens": 5,
            "cost_usd": None,
        }

    return invoke


def read(key):
    return "read_evidence", {"evidence_id": key, "reason": "模拟：核对条款与门店类别"}


class ToolBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def run_c(self, *actions, case="BF26-02", **options):
        return await agent.llm(
            api.cases[case], api.docs, "mock/fixture", fake(*actions), **options
        )

    async def test_normal_and_visible_context(self):
        inputs = []
        complete = fake(read("E03"), read("E04"), read("E07"))

        async def inspect(model, messages, timeout):
            inputs.append(json.loads(messages[1]["content"]))
            return await complete(model, messages, timeout)

        row = await agent.llm(api.cases["BF26-02"], api.docs, "mock/fixture", inspect)
        self.assertEqual(row.label, "不适用")
        # The verdict comes after E04; the shared stop policy then allows one
        # check read, and only E07 may state the same offer.
        self.assertEqual((row.query_count, row.model_calls), (3, 3))
        self.assertEqual(row.stop_reason, "补查完成")
        self.assertEqual(row.citations, ["E03", "E04"])
        self.assertEqual([u["id"] for u in inputs[2]["unread"]], ["E07"])
        self.assertIn("check_read", inputs[2])
        self.assertIsNone(row.cost_usd)
        self.assertEqual(inputs[0]["read"], [])
        self.assertEqual(set(inputs[0]["unread"][0]), {"id", "source_type", "title"})
        self.assertEqual([s["id"] for s in inputs[1]["read"]], ["E03"])
        self.assertIn("passages", inputs[1]["read"][0])

    async def test_invalid_arguments_and_ids(self):
        for action in [
            read("E02"),
            ("read_evidence", {"evidence_id": 12, "reason": "x"}),
            ("read_evidence", {}),
            ("override_label", {"reason": "x"}),
        ]:
            r = await self.run_c(action)
            self.assertEqual((r.status, r.query_count, r.model_calls), ("error", 0, 1))
        r = await self.run_c(read("E03"), read("E03"))
        self.assertEqual((r.status, r.query_count, r.model_calls), ("error", 1, 2))

    async def test_timeout_and_upstream(self):
        async def slow(*args):
            await asyncio.sleep(1)

        r = await agent.llm(api.cases["BF26-02"], api.docs, "mock", slow, timeout=0.01)
        self.assertEqual((r.stop_reason, r.model_calls), ("模型超时", 1))
        r = await self.run_c(RuntimeError("private provider details"))
        self.assertEqual(r.stop_reason, "上游模型请求失败")
        self.assertNotIn("private", r.model_dump_json())

    async def test_separate_budgets_and_finish(self):
        r = await self.run_c(read("E03"), call_limit=1)
        self.assertEqual((r.stop_reason, r.model_calls), ("模型调用预算用尽", 1))
        r = await self.run_c(read("E01"), read("E03"), read("E07"))
        self.assertEqual((r.stop_reason, r.query_count), ("文档预算用尽", 3))
        r = await self.run_c(("finish", {"reason": "没有进一步依据"}))
        self.assertEqual((r.label, r.query_count), ("证据不足", 0))

    async def test_other_cases_mock_only(self):
        for key, ids, label in [
            ("BF26-01", ["E02", "E07"], "适用"),
            ("BF26-03", ["E05", "E07", "E06"], "证据不足"),
        ]:
            r = await self.run_c(*(read(i) for i in ids), case=key)
            self.assertEqual(r.label, label)
            self.assertEqual(r.model, "mock/fixture")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)

    def test_catalog_offline_and_unavailable(self):
        with patch.dict("os.environ", {}, clear=True):
            cat = self.client.get("/api/cases").json()
            self.assertEqual(len(cat["cases"]), 3)
            self.assertFalse(cat["llm_available"])
            for c in cat["cases"]:
                for arm in ("A", "B", "C"):
                    response = self.client.post(
                        f"/api/cases/{c['case_id']}/run", json={"strategy": arm}
                    )
                    self.assertEqual(response.status_code, 200)
                    r = response.json()
                    self.assertEqual(r["query_count"], len(r["steps"]))
                    self.assertEqual(r["model_calls"], 0)
                    if arm == "C":
                        self.assertIsNone(r["label"])
                        self.assertEqual(r["status"], "unavailable")
                    for s in r["steps"]:
                        self.assertEqual(s["source_id"], s["evidence"]["id"])
                        self.assertTrue(s["evidence"]["url"].startswith("https://"))

    def test_errors(self):
        for key, arm, status in [("bad", "A", 404), ("BF26-02", "D", 422)]:
            r = self.client.post(f"/api/cases/{key}/run", json={"strategy": arm})
            self.assertEqual(r.status_code, status)
            self.assertIsInstance(r.json()["detail"], str)
