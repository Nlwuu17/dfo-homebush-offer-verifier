"""Record/replay for arm C. Uses scripted replies only; no model is called.

Imports only v02.agent and v02.cassette, so these tests run without FastAPI.
"""

import asyncio
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from bf26 import DATA, inputs
from v02 import agent, cassette

CASES, DOCS = inputs(DATA)


def scripted(*actions, model="deepseek-flash", cost=0.00008):
    pending = iter(actions)

    async def invoke(configured, messages, timeout):
        action = next(pending)
        if isinstance(action, Exception):
            raise action
        if action == "slow":
            await asyncio.sleep(1)
        tool, args = action
        return {
            "model": model,
            "tools": [{"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}],
            "input_tokens": 900,
            "output_tokens": 40,
            "cost_usd": cost,
        }

    return invoke


def read(key):
    return "read_evidence", {"evidence_id": key, "reason": "核对条款与门店类别"}


async def record(*actions, case="BF26-02", **options):
    # These tests exercise recording itself, so they keep the policy the
    # scripted replies were written for: stop at the first verdict.
    options.setdefault("policy", "first_verdict")
    return await cassette.record_run(
        CASES[case], DOCS, "deepseek/deepseek-chat", scripted(*actions), 1, **options
    )


class RecordReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_replay_reproduces_recorded_result(self):
        entry = await record(read("E03"), read("E04"))
        result = entry["result"]
        self.assertEqual((result["label"], result["citations"]), ("不适用", ["E03", "E04"]))
        self.assertEqual(entry["configured_model"], "deepseek/deepseek-chat")
        self.assertEqual([c["model"] for c in result["calls"]], ["deepseek-flash"] * 2)
        self.assertEqual(len(entry["replies"]), 2)

        replayed, problems = await cassette.replay_run(entry, CASES, DOCS)
        self.assertEqual(problems, [])
        self.assertEqual(replayed.model_dump(mode="json"), result)

    async def test_cassette_file_round_trip_is_byte_stable(self):
        entry = await record(read("E03"), read("E04"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.jsonl"
            path.write_text(cassette.dump(entry), encoding="utf-8")
            loaded = cassette.load(path)[0]
            replayed, problems = await cassette.replay_run(loaded, CASES, DOCS)
            self.assertEqual(problems, [])
            rebuilt = dict(loaded, result=replayed.model_dump(mode="json"))
            self.assertEqual(cassette.dump(rebuilt), path.read_text(encoding="utf-8"))

    async def test_cassette_stores_no_secrets_or_provider_errors(self):
        ok = await record(read("E03"), read("E04"))
        failed = await record(read("E03"), RuntimeError("sk-secret provider detail"))
        text = cassette.dump(ok) + cassette.dump(failed)
        self.assertNotIn("api_key", text)
        self.assertNotIn("sk-secret", text)
        self.assertEqual(failed["replies"][-1], {
            "request_sha256": failed["replies"][-1]["request_sha256"],
            "error": "upstream",
        })

    async def test_recorded_failures_replay(self):
        upstream = await record(read("E03"), RuntimeError("boom"))
        replayed, problems = await cassette.replay_run(upstream, CASES, DOCS)
        self.assertEqual(problems, [])
        self.assertEqual(replayed.stop_reason, "上游模型请求失败")

        timeout = await record(read("E03"), "slow", timeout=0.01)
        self.assertEqual(timeout["result"]["stop_reason"], "模型超时")
        self.assertEqual(timeout["replies"][-1]["error"], "timeout")
        replayed, problems = await cassette.replay_run(timeout, CASES, DOCS)
        self.assertEqual(problems, [])
        self.assertEqual(replayed.model_dump(mode="json"), timeout["result"])

    async def test_changed_inputs_are_detected(self):
        entry = await record(read("E03"), read("E04"))
        docs = copy.deepcopy(DOCS)
        docs["E03"]["passages"][0]["summary_zh"] += "（已修改）"
        _, problems = await cassette.replay_run(entry, CASES, docs)
        self.assertIn("第 2 次模型请求与录制时不一致", problems)

    async def test_edited_replies_and_results_are_detected(self):
        entry = await record(read("E03"), read("E04"))

        edited = copy.deepcopy(entry)
        edited["replies"][0]["reply"]["tools"][0]["arguments"] = json.dumps(
            {"evidence_id": "E07", "reason": "改动"}, ensure_ascii=False
        )
        _, problems = await cassette.replay_run(edited, CASES, DOCS)
        self.assertTrue(problems)

        edited = copy.deepcopy(entry)
        edited["result"]["label"] = "适用"
        _, problems = await cassette.replay_run(edited, CASES, DOCS)
        self.assertEqual(problems, ["回放结果与录制结果不一致"])

        extra = copy.deepcopy(entry)
        extra["replies"].append(copy.deepcopy(extra["replies"][-1]))
        _, problems = await cassette.replay_run(extra, CASES, DOCS)
        self.assertIn("回放结束时仍有未使用的录制响应", problems)

        short = copy.deepcopy(entry)
        short["replies"].pop()
        _, problems = await cassette.replay_run(short, CASES, DOCS)
        self.assertIn("回放请求超过录制的模型调用次数", problems)

    async def test_summary_counts_paths_and_correctness(self):
        a = await record(read("E03"), read("E04"))
        b = await record(read("E03"), read("E07"), read("E04"))
        b["run_index"] = 2
        text = cassette.summarise([a, b], {"BF26-02": "不适用"})
        self.assertIn("| BF26-02 | 不适用 | 2 | 2/2 |", text)
        self.assertIn("E03 → E04（1）；E03 → E07 → E04（1）", text)
        self.assertIn("| 2.50 | 2.50 |", text)
        self.assertIn("供应商返回的模型：deepseek-flash", text)
        self.assertEqual(text, cassette.summarise([a, b], {"BF26-02": "不适用"}))

    async def test_unknown_schema_or_case(self):
        entry = await record(read("E03"), read("E04"))
        _, problems = await cassette.replay_run(dict(entry, schema=99), CASES, DOCS)
        self.assertEqual(problems, ["不支持的录制格式：99"])
        _, problems = await cassette.replay_run(dict(entry, case_id="X"), CASES, DOCS)
        self.assertEqual(problems, ["找不到案例 X"])


CANDIDATES = "data/candidates_2026_11_26"


class CandidateRecordingTests(unittest.IsolatedAsyncioTestCase):
    async def test_dataset_is_stored_and_replayed(self):
        folder = cassette.ROOT / CANDIDATES
        cases, docs = inputs(folder)
        entry = await cassette.record_run(
            cases["NC13"], docs, "deepseek/deepseek-chat",
            scripted(read("N10"), read("N11")), 1,
            dataset=CANDIDATES, split="dev",
        )
        self.assertEqual((entry["dataset"], entry["split"]), (CANDIDATES, "dev"))
        self.assertEqual(cassette.dataset_of(entry), CANDIDATES)
        _, problems = await cassette.replay_run(entry, cases, docs)
        self.assertEqual(problems, [])

    async def test_old_entries_default_to_bf26(self):
        entry = await record(read("E03"), read("E04"))
        self.assertNotIn("dataset", entry)
        self.assertEqual(cassette.dataset_of(entry), "data/real_cases_2026_11_26")

    async def test_unlabelled_cases_are_not_scored(self):
        entry = await record(read("E03"), read("E04"))
        text = cassette.summarise([entry], {"BF26-02": None})
        self.assertIn("| BF26-02 | 未标注 | 1 | — |", text)
        self.assertIn("| 合计 | — | 1 | 0/0 |", text)
        self.assertIn("未标注案例的运行：1/1", text)


class CommandLineTests(unittest.TestCase):
    def test_heldout_cases_need_explicit_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "c.jsonl")
            with self.assertRaises(SystemExit) as stop:
                cassette.main(["record", "--out", out, "--data", CANDIDATES,
                               "--case", "NC03"])
            self.assertIn("留出集需显式指定", str(stop.exception))
            self.assertFalse(Path(out).exists())

    def test_replay_finds_each_entrys_dataset(self):
        folder = cassette.ROOT / CANDIDATES
        cases, docs = inputs(folder)
        bf26_entry = asyncio.run(record(read("E03"), read("E04")))
        cand_entry = asyncio.run(cassette.record_run(
            cases["NC13"], docs, "deepseek/deepseek-chat",
            scripted(read("N10"), read("N11")), 2,
            dataset=CANDIDATES, split="dev",
        ))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.jsonl"
            path.write_text(cassette.dump(bf26_entry) + cassette.dump(cand_entry), "utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                cassette.main(["replay", str(path)])  # exits non-zero on mismatch
            self.assertIn("2/2 次运行回放一致", output.getvalue())
            with self.assertRaises(SystemExit) as stop:
                cassette.main(["report", str(path)])
            self.assertIn("一次只能汇总一个数据集", str(stop.exception))


class ConfirmPolicyTests(unittest.IsolatedAsyncioTestCase):
    """Arm C under the shared stop policy: one check read after a verdict."""

    async def test_check_read_is_offered_only_relevant_candidates(self):
        payloads = []
        replies = scripted(read("E03"), read("E04"), read("E07"))

        async def invoke(model, messages, timeout):
            payloads.append(json.loads(messages[1]["content"]))
            return await replies(model, messages, timeout)

        r = await agent.llm(CASES["BF26-02"], DOCS, "deepseek/deepseek-chat", invoke)
        self.assertEqual((r.label, r.query_count, r.model_calls), ("不适用", 3, 3))
        self.assertEqual(r.stop_reason, "补查完成")
        self.assertTrue(r.steps[2].selection_reason.startswith("补查同一优惠："))
        self.assertNotIn("check_read", payloads[1])
        self.assertIn("check_read", payloads[2])
        self.assertEqual([u["id"] for u in payloads[2]["unread"]], ["E07"])

    async def test_check_read_of_an_irrelevant_source_is_refused(self):
        r = await agent.llm(
            CASES["BF26-02"], DOCS, "m", scripted(read("E03"), read("E04"), read("E01"))
        )
        self.assertEqual(r.status, "error")
        self.assertTrue(r.stop_reason.startswith("工具调用被拒绝：补查只能读取"))
        self.assertEqual(r.query_count, 2)

    async def test_first_verdict_policy_keeps_the_old_stop(self):
        r = await agent.llm(
            CASES["BF26-02"], DOCS, "m", scripted(read("E03"), read("E04")),
            policy="first_verdict",
        )
        self.assertEqual((r.stop_reason, r.query_count), ("证据充分", 2))
        with self.assertRaises(ValueError):
            await agent.llm(CASES["BF26-02"], DOCS, "m", scripted(), policy="never")

    async def test_policy_is_recorded_and_replayed(self):
        entry = await cassette.record_run(
            CASES["BF26-02"], DOCS, "deepseek/deepseek-chat",
            scripted(read("E03"), read("E04"), read("E07")), 1,
        )
        self.assertEqual(entry["stop_policy"], "confirm")
        _, problems = await cassette.replay_run(entry, CASES, DOCS)
        self.assertEqual(problems, [])

    async def test_entries_without_a_policy_replay_as_first_verdict(self):
        entry = await record(read("E03"), read("E04"))
        legacy = {k: v for k, v in entry.items() if k != "stop_policy"}
        _, problems = await cassette.replay_run(legacy, CASES, DOCS)
        self.assertEqual(problems, [])


class CommitNoticeTests(unittest.TestCase):
    def test_same_commit_prints_nothing(self):
        here = cassette.source_revision()
        if here is None:
            self.skipTest("not in a Git checkout")
        self.assertEqual(cassette.commit_notice([{"source": here}], "x.jsonl"), [])

    def test_other_commit_names_both_and_the_switch_command(self):
        here = cassette.source_revision()
        if here is None:
            self.skipTest("not in a Git checkout")
        old = "0" * 40
        lines = cassette.commit_notice([{"source": {"commit": old}}], "c.jsonl")
        text = "\n".join(lines)
        self.assertIn(here["commit"], text)
        self.assertIn(old, text)
        self.assertIn(f"git worktree add --detach /tmp/replay-0000000 {old}", text)
        self.assertIn(str(Path("c.jsonl").resolve()), text)
        self.assertIn("不作为权威核验", text)


if __name__ == "__main__":
    unittest.main()
