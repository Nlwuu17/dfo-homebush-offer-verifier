"""Record real arm-C model replies and replay them offline.

A cassette is a JSONL file with one line per run. Each line stores the
recorded model replies together with the result the agent returned. Replay
feeds the same replies back through the unchanged agent loop without calling
a model. It then checks that every request matches the recorded request and
that the rebuilt result equals the recorded one. Wall-clock latency cannot be
reproduced, so replay copies the recorded latencies and everything else must
match byte for byte.

Usage (from the repository root):

    python -m v02.cassette record --out results/c_arm/cassette.jsonl --repeats 5
    python -m v02.cassette replay results/c_arm/cassette.jsonl
    python -m v02.cassette report results/c_arm/cassette.jsonl

Other datasets are recorded with --data; datasets with splits.json default to
the dev split, and the held-out split is only recorded when named. Each run
stores its dataset, so replay and report find the right inputs on their own.

Recording needs DFO_MODEL, the matching API key and LiteLLM. Replay needs
neither. Cassettes never contain API keys: only the chat messages, the tool
calls, token counts, cost and model names are stored.
"""

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from bf26 import DATA, ROOT, index, inputs, select
from bf26 import load as load_json
from . import agent
from .schema import Result

SCHEMA = 1
REPLY_KEYS = {"model", "tools", "cost_usd", "input_tokens", "output_tokens"}


class ReplayMismatch(Exception):
    """The replayed run asked for something the recording did not contain."""


def fingerprint(model, messages):
    text = json.dumps(
        {"model": model, "messages": messages}, ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(text.encode()).hexdigest()


def recording(invoke, replies):
    """Wrap invoke so that every call, including failed ones, is appended.

    Failures keep only their kind ("timeout" or "upstream"), never the
    provider's error text, matching what the agent itself exposes.
    """

    async def wrapped(model, messages, timeout):
        entry = {"request_sha256": fingerprint(model, messages)}
        try:
            reply = await invoke(model, messages, timeout)
        except asyncio.CancelledError:
            # asyncio.wait_for cancels the call when the agent's timeout fires.
            replies.append({**entry, "error": "timeout"})
            raise
        except Exception as exc:
            timeout_like = (
                isinstance(exc, TimeoutError)
                or "timeout" in type(exc).__name__.lower()
            )
            replies.append({**entry, "error": "timeout" if timeout_like else "upstream"})
            raise
        replies.append({**entry, "reply": {k: reply.get(k) for k in sorted(REPLY_KEYS)}})
        return reply

    return wrapped


def replaying(replies, problems):
    """Return recorded replies in order and log any divergence in problems.

    The agent turns exceptions raised by invoke into an ordinary upstream
    error, so divergence is reported through problems as well as raised.
    """
    pending = iter(enumerate(replies, 1))

    async def invoke(model, messages, timeout):
        try:
            number, entry = next(pending)
        except StopIteration:
            problems.append("回放请求超过录制的模型调用次数")
            raise ReplayMismatch(problems[-1])
        if entry["request_sha256"] != fingerprint(model, messages):
            problems.append(f"第 {number} 次模型请求与录制时不一致")
            raise ReplayMismatch(problems[-1])
        if entry.get("error") == "timeout":
            raise TimeoutError("recorded timeout")
        if entry.get("error"):
            raise RuntimeError("recorded upstream failure")
        return json.loads(json.dumps(entry["reply"]))

    invoke.unused = lambda: sum(1 for _ in pending)
    return invoke


def source_revision():
    """The code revision a recording was made with, or None outside Git."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return {"commit": sha, "dirty": bool(dirty)}


def relative(folder):
    """A dataset folder as stored in cassettes: a POSIX path under the repo."""
    try:
        return Path(folder).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        raise ValueError(f"数据目录必须在仓库内：{folder}") from None


def dataset_of(entry):
    """Entries recorded before datasets were stored belong to BF26."""
    return entry.get("dataset", relative(DATA))


# Entries recorded before stop policies existed stopped at the first verdict.
LEGACY_POLICY = "first_verdict"


async def record_run(
    case, docs, model, invoke, run_index, *, dataset=None, split=None,
    policy="confirm", **options
):
    replies = []
    result = await agent.llm(
        case, docs, model, recording(invoke, replies), policy=policy, **options
    )
    where = {} if dataset is None else {"dataset": dataset, "split": split}
    return {
        **where,
        "schema": SCHEMA,
        "case_id": case["case_id"],
        "run_index": run_index,
        "configured_model": model,
        "stop_policy": policy,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source_revision(),
        "replies": replies,
        "result": result.model_dump(mode="json"),
    }


async def replay_run(entry, cases, docs, **options):
    """Rebuild one recorded run. Returns (result, problems)."""
    if entry.get("schema") != SCHEMA:
        return None, [f"不支持的录制格式：{entry.get('schema')!r}"]
    if entry["case_id"] not in cases:
        return None, [f"找不到案例 {entry['case_id']}"]
    problems = []
    invoke = replaying(entry["replies"], problems)
    result = await agent.llm(
        cases[entry["case_id"]],
        docs,
        entry["configured_model"],
        invoke,
        policy=entry.get("stop_policy", LEGACY_POLICY),
        **options,
    )
    if invoke.unused():
        problems.append("回放结束时仍有未使用的录制响应")
    recorded = Result.model_validate(entry["result"])
    if len(result.calls) == len(recorded.calls):
        for call, old in zip(result.calls, recorded.calls):
            call.latency_ms = old.latency_ms
    result.latency_ms = recorded.latency_ms
    if not problems and result.model_dump(mode="json") != entry["result"]:
        problems.append("回放结果与录制结果不一致")
    return result, problems


def rejudge(entry, cases, docs, judge=None):
    """Judge a recorded run again on its fixed read path, with no model call.

    The documents and their order come from the recording; only the judge is
    the current one. This answers whether the same evidence is now judged
    better. A live run could stop earlier or read on, so the step at which
    the current judge first reaches a verdict is reported too.
    """
    from bf26 import UNKNOWN, assess

    judge = judge or assess
    case = cases[entry["case_id"]]
    path = [s["source_id"] for s in entry["result"]["steps"]]
    read, first = [], None
    label, basis, refs = UNKNOWN, "", []
    for number, key in enumerate(path, 1):
        read.append(docs[key])
        label, basis, refs, _ = judge(case, read)
        if first is None and label != UNKNOWN:
            first = number
    return {
        "case_id": entry["case_id"],
        "run_index": entry.get("run_index"),
        "path": path,
        "label": label,
        "reason": basis,
        "citations": refs,
        "first_verdict_step": first,
        "recorded_label": entry["result"]["label"],
        "recorded_policy": entry.get("stop_policy", LEGACY_POLICY),
        "recorded_commit": (entry.get("source") or {}).get("commit"),
    }


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def dump(entry):
    return json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"


async def record_main(args):
    dataset = relative(args.data)
    cases, docs = inputs(args.data)
    pool = select(args.data, cases, args.split)
    chosen = args.case or list(pool)
    for key in chosen:
        if key not in cases:
            sys.exit(f"找不到案例 {key}")
        if key not in pool:
            sys.exit(f"{key} 不在 {args.split} 划分中；留出集需显式指定 --split heldout")
    if not chosen:
        sys.exit("该划分没有案例")
    model, reason = agent.configuration()
    if reason:
        sys.exit(f"无法录制：{reason}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    start = len(load(out)) if out.exists() else 0
    with open(out, "a", encoding="utf-8") as f:
        index = start
        for key in chosen:
            for _ in range(args.repeats):
                index += 1
                entry = await record_run(
                    cases[key],
                    docs,
                    model,
                    agent.completion,
                    index,
                    dataset=dataset,
                    split=args.split,
                )
                f.write(dump(entry))
                f.flush()
                r = entry["result"]
                path = " → ".join(s["source_id"] for s in r["steps"]) or "无"
                print(
                    f"#{index} {key} {r['status']} {r['label']} 路径 {path}"
                    f" 模型调用 {r['model_calls']} 耗时 {r['latency_ms']} ms"
                    f" 费用 {r['cost_usd']}"
                )


def commit_notice(entries, cassette):
    """Lines to print when the code differs from the commit a run was recorded at.

    Replay is authoritative only at the recorded commit: other code may judge
    differently, stop at another point or send other requests, so a result
    here says nothing about the recording itself.
    """
    here = source_revision()
    recorded = sorted(
        {(e.get("source") or {}).get("commit") or "未记录" for e in entries}
    )
    head = here["commit"] if here else None
    if head and recorded == [head]:
        return []
    path = Path(cassette).resolve()
    lines = [
        f"当前提交：{head or '无法确定（不在 Git 仓库中）'}",
        f"录制提交：{'、'.join(recorded)}",
        "当前代码与录制提交不同，以下回放结果不作为权威核验。权威回放请在录制提交上运行：",
    ]
    for commit in recorded:
        if commit == "未记录":
            lines.append("  （部分条目未记录提交，无法给出切换命令）")
            continue
        short = commit[:7]
        lines.append(
            f"  git worktree add --detach /tmp/replay-{short} {commit} && "
            f"(cd /tmp/replay-{short} && python -m v02.cassette replay {path})"
        )
    return lines


async def replay_main(args):
    failed = 0
    entries = load(args.cassette)
    for line in commit_notice(entries, args.cassette):
        print(line)
    loaded = {}
    for entry in entries:
        dataset = dataset_of(entry)
        if dataset not in loaded:
            loaded[dataset] = inputs(ROOT / dataset)
        _, problems = await replay_run(entry, *loaded[dataset])
        tag = f"#{entry.get('run_index')} {entry.get('case_id')}"
        if problems:
            failed += 1
            print(f"{tag} 不一致：" + "；".join(problems))
        else:
            print(f"{tag} 一致")
    print(f"{len(entries) - failed}/{len(entries)} 次运行回放一致")
    if failed:
        sys.exit(1)


def summarise(entries, gold):
    """Deterministic Markdown summary of recorded runs against reference labels."""
    by_case = {}
    for entry in entries:
        by_case.setdefault(entry["case_id"], []).append(entry)
    lines = [
        "# C 组录制结果汇总",
        "",
        "由 `python -m v02.cassette report` 从录制文件生成。耗时为录制时的墙钟时间；费用为 LiteLLM 报告值，未与供应商账单核对。",
        "",
        "| 案例 | 人工标签 | 运行次数 | 判定正确 | 读取路径（次数） | 平均读取份数 | 平均模型调用 | 平均耗时 (ms) | 费用合计 (USD) |",
        "|---|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    totals = dict(runs=0, scored=0, correct=0, reads=0, calls=0, ms=0, cost=0.0)
    cost_known = True
    for key in sorted(by_case):
        runs = [e["result"] for e in by_case[key]]
        n = len(runs)
        paths = {}
        for r in runs:
            path = " → ".join(s["source_id"] for s in r["steps"]) or "无"
            paths[path] = paths.get(path, 0) + 1
        label = gold[key]
        correct = sum(r["label"] == label for r in runs) if label else 0
        reads = sum(r["query_count"] for r in runs)
        calls = sum(r["model_calls"] for r in runs)
        ms = sum(r["latency_ms"] for r in runs)
        costs = [r["cost_usd"] for r in runs]
        known = all(c is not None for c in costs)
        cost_known &= known
        cost = sum(costs) if known else None
        lines.append(
            f"| {key} | {label or '未标注'} | {n} | "
            + (f"{correct}/{n}" if label else "—")
            + " | "
            + "；".join(f"{p}（{c}）" for p, c in sorted(paths.items()))
            + f" | {reads / n:.2f} | {calls / n:.2f} | {ms / n:.0f} | "
            + (f"{cost:.6f}" if known else "未知")
            + " |"
        )
        totals.update(
            runs=totals["runs"] + n,
            scored=totals["scored"] + (n if label else 0),
            correct=totals["correct"] + correct,
            reads=totals["reads"] + reads,
            calls=totals["calls"] + calls,
            ms=totals["ms"] + ms,
            cost=totals["cost"] + (cost or 0.0),
        )
    n = totals["runs"]
    lines.append(
        f"| 合计 | — | {n} | {totals['correct']}/{totals['scored']} | — | {totals['reads'] / n:.2f} | "
        f"{totals['calls'] / n:.2f} | {totals['ms'] / n:.0f} | "
        + (f"{totals['cost']:.6f}" if cost_known else "未知")
        + " |"
    )
    configured = sorted({e["configured_model"] for e in entries})
    provider = sorted({c["model"] for e in entries for c in e["result"]["calls"]})
    commits = sorted(
        {(e.get("source") or {}).get("commit", "未记录")[:7] for e in entries}
    )
    dirty = sum(bool((e.get("source") or {}).get("dirty")) for e in entries)
    stamps = sorted(e["recorded_at"] for e in entries)
    statuses = {}
    for e in entries:
        statuses[e["result"]["status"]] = statuses.get(e["result"]["status"], 0) + 1
    places = sorted(
        {(e["dataset"], e.get("split") or "—") for e in entries if "dataset" in e}
    )
    lines += [""]
    if places:
        lines.append(
            "- 数据集：" + "、".join(f"{d}（{s}）" for d, s in places)
        )
    if totals["scored"] < n:
        lines.append(
            f"- 判定正确只统计已标注案例的运行；未标注案例的运行：{n - totals['scored']}/{n}"
        )
    lines += [
        f"- 配置的模型：{'、'.join(configured)}；供应商返回的模型：{'、'.join(provider)}",
        f"- 代码提交：{'、'.join(commits)}；工作区有未提交改动的运行：{dirty}/{n}",
        f"- 录制时间（UTC）：{stamps[0]} 至 {stamps[-1]}",
        "- 运行状态：" + "、".join(f"{k} {v}" for k, v in sorted(statuses.items())),
    ]
    return "\n".join(lines) + "\n"


async def report_main(args):
    entries = load(args.cassette)
    if not entries:
        sys.exit("录制文件为空")
    datasets = {dataset_of(e) for e in entries}
    if len(datasets) != 1:
        sys.exit(f"一次只能汇总一个数据集的录制：{sorted(datasets)}")
    folder = ROOT / datasets.pop()
    labels = index(load_json(folder / args.labels), "case_id")
    for key, row in labels.items():
        if row["label"] not in (None, "适用", "不适用", "证据不足"):
            sys.exit(f"{key} 的标签无效：{row['label']!r}")
    gold = {k: v["label"] for k, v in labels.items()}
    unknown = {e["case_id"] for e in entries} - gold.keys()
    if unknown:
        sys.exit(f"录制文件含无标签案例：{sorted(unknown)}")
    text = summarise(entries, gold)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")


def main(argv=None):
    parser = argparse.ArgumentParser(description="录制或回放 C 组的真实模型运行")
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="调用真实模型并追加到录制文件")
    rec.add_argument("--out", required=True)
    rec.add_argument("--case", action="append", help="可重复；默认全部案例")
    rec.add_argument("--repeats", type=int, default=1)
    rec.add_argument("--data", type=Path, default=DATA, help="数据目录，默认 BF26")
    rec.add_argument("--split", choices=["dev", "heldout", "all"], default="dev",
                     help="有 splits.json 的数据集默认只录开发集")
    rep = sub.add_parser("replay", help="不调用模型，逐次回放并校验")
    rep.add_argument("cassette")
    summ = sub.add_parser("report", help="按人工标签汇总录制结果")
    summ.add_argument("cassette")
    summ.add_argument("--out", help="同时写入 Markdown 文件")
    summ.add_argument("--labels", default="gold_labels.json",
                      help="数据目录内的标签文件名；未标注（null）的案例不计分")
    args = parser.parse_args(argv)
    if args.command == "record" and args.repeats < 1:
        parser.error("--repeats 至少为 1")
    run = {"record": record_main, "replay": replay_main, "report": report_main}[
        args.command
    ]
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
