"""DFO Homebush 优惠核对与可靠性评测 CLI."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from time import perf_counter

from providers import Provider
from verify_offer import FROZEN, ROOT, NO, YES, Reader, decide, inspect, load


def verify_freeze():
    manifest = load(ROOT / "data/freeze.json")
    for path, expected in manifest.items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
            raise ValueError("冻结文件校验失败：" + path)
    return hashlib.sha256((ROOT / "data/freeze.json").read_bytes()).hexdigest()


def stop(label, used, count, budget):
    if label in (YES, NO):
        return "确认标准已满足"
    if used == count:
        return "候选已读完"
    if used == budget:
        return "预算用尽"
    return None


def run(case, documents, policy, arm, model, digest):
    public = {k: case[k] for k in ("brand", "offer", "day", "event", "centre")}
    catalogue = case["catalogue"]
    reader = Reader(catalogue, documents, policy["budget"])
    provider = Provider(model)
    steps, evidence = [], []
    start = perf_counter()
    while True:
        unread = [r for r in catalogue if r["id"] not in reader.seen]
        if arm == "A":
            row = min(unread, key=lambda d: policy["fixed_order"].index(d["type"]))
            key, reason = row["id"], "按预定来源顺序和目录顺序读取"
        else:
            key, reason = provider.select(public, unread, evidence)
        doc = reader.read(key)
        record = inspect(public, doc, provider.extract(public, doc))
        evidence.append(record)
        label, basis = decide(evidence)
        steps.append(
            dict(id=key, reason=reason, evidence=record, label=label, basis=basis)
        )
        end = stop(label, len(steps), len(catalogue), reader.budget)
        if end:
            return dict(
                case=case["id"],
                split=case["split"],
                arm=arm,
                mode="model" if model else "fixture",
                model=model,
                freeze=digest,
                steps=steps,
                label=label,
                stop=end,
                calls=provider.calls,
                seconds=perf_counter() - start,
            )


def replay(trace, case, documents, policy, digest):
    if trace["freeze"] != digest or not trace["steps"]:
        raise ValueError("轨迹版本或步数无效")
    reader = Reader(case["catalogue"], documents, policy["budget"])
    records = []
    for i, s in enumerate(trace["steps"]):
        if trace["arm"] == "A":
            unread = [r for r in case["catalogue"] if r["id"] not in reader.seen]
            expected = min(unread, key=lambda d: policy["fixed_order"].index(d["type"]))
            if expected["id"] != s["id"]:
                raise ValueError("固定顺序不符")
        doc = reader.read(s["id"])
        record = inspect(case, doc, s["evidence"]["citations"])
        records.append(record)
        label, basis = decide(records)
        end = stop(label, len(records), len(case["catalogue"]), reader.budget)
        if (record, label, basis) != (s["evidence"], s["label"], s["basis"]) or bool(
            end
        ) != (i == len(trace["steps"]) - 1):
            raise ValueError("轨迹证据、判断或提前停止条件不一致")
    if (end, label) != (trace["stop"], trace["label"]):
        raise ValueError("轨迹终点不一致")


def score(trace, ref):
    steps = trace["steps"]
    gold = ref["label"]
    correct = trace["label"] == gold
    located = {
        s["id"] + "#" + c["location"]
        for s in steps
        for c in s["evidence"]["citations"]
        if c["complete"]
    }
    missing = sorted(set(ref["evidence"]) - located)
    read = {s["id"] for s in steps}
    stage = "符合参考标注"
    if any(key.split("#")[0] not in read for key in missing):
        stage = "选择或停止时尚未读取参考证据"
    elif missing:
        stage = "抽取或引用缺失"
    elif not correct:
        stage = "证据解释或规则不符"
    return dict(
        gold=gold,
        correct=correct,
        supported=correct and not missing,
        missing=missing,
        reference_reason=ref["reason"],
        diagnosis=stage,
    )


def ratio(a, b):
    return f"{a}/{b} ({a / b:.1%})" if b else "0/0 (N/A)"


def tables(traces):
    lines = [
        "# 对照结果",
        "",
        "固定响应回放，真实模型对照尚未运行。"
        if traces[0]["mode"] == "fixture"
        else "本地模型：" + traces[0]["model"],
        "",
        "| 样本 | 组 | 准确率 | 误确认率 | 漏确认率 | 错判不适用率 | 平均读取 | 引用可定位率 | 证据支持 | 模型调用 抽取/选文 | token 入/出 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    timing = [
        "| 样本 | 组 | 总墙钟 ms | 选文 ms | 抽取 ms |",
        "|---|---|---:|---:|---:|",
    ]
    for split in ("real", "synthetic"):
        for arm in ("A", "B"):
            rows = [t for t in traces if t["split"] == split and t["arm"] == arm]
            n = len(rows)

            def count(fn):
                return sum(fn(t["label"], t["score"]["gold"]) for t in rows)

            citations = [
                c for t in rows for s in t["steps"] for c in s["evidence"]["citations"]
            ]
            calls = [c for t in rows for c in t["calls"]]
            models = [c for c in calls if c["model"]]
            reads = sum(len(t["steps"]) for t in rows)
            name = "真实" if split == "real" else "合成"
            cells = [
                name,
                arm,
                ratio(count(lambda p, g: p == g), n),
                ratio(
                    count(lambda p, g: p == YES and g != YES),
                    count(lambda p, g: g != YES),
                ),
                ratio(
                    count(lambda p, g: p != YES and g == YES),
                    count(lambda p, g: g == YES),
                ),
                ratio(
                    count(lambda p, g: p == NO and g != NO), count(lambda p, g: g != NO)
                ),
                f"{reads}/{n} ({reads / n:.2f})",
                ratio(sum(c["found"] for c in citations), len(citations)),
                ratio(sum(t["score"]["supported"] for t in rows), n),
                "/".join(
                    str(sum(c["role"] == r for c in models))
                    for r in ("extract", "select")
                ),
                "/".join(str(sum(c[k] for c in calls)) for k in ("input", "output")),
            ]
            lines.append("| " + " | ".join(cells) + " |")
            times = [sum(t["seconds"] for t in rows)] + [
                sum(c["seconds"] for c in calls if c["role"] == r)
                for r in ("select", "extract")
            ]
            timing.append(
                "| "
                + " | ".join([name, arm] + [f"{v * 1000:.3f}" for v in times])
                + " |"
            )
    return "\n".join(lines) + "\n", "\n".join(timing) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="action", required=True)
    ev = cmds.add_parser("eval")
    ev.add_argument("--out", type=Path, default=ROOT / "results")
    one = cmds.add_parser("check")
    one.add_argument("case")
    one.add_argument("--arm", choices=["A", "B"], default="B")
    for cmd in (ev, one):
        cmd.add_argument("--local-model", help="已安装的 Ollama 本机模型名称")
    rp = cmds.add_parser("replay")
    rp.add_argument("trace", type=Path)
    args = parser.parse_args()
    digest = verify_freeze()
    policy, documents, cases = (
        load(ROOT / "policy.json"),
        load(FROZEN / "documents.json"),
        load(FROZEN / "cases.json"),
    )
    by_id = {c["id"]: c for c in cases}

    def dump(value):
        return json.dumps(value, ensure_ascii=False)

    if args.action == "check":
        print(
            json.dumps(
                run(
                    by_id[args.case],
                    documents,
                    policy,
                    args.arm,
                    args.local_model,
                    digest,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.action == "replay":
        rows = [json.loads(line) for line in args.trace.read_text().splitlines()]
        if not rows:
            raise ValueError("空轨迹")
        for row in rows:
            replay(row, by_id[row["case"]], documents, policy, digest)
            print(
                row["case"],
                row["arm"],
                " → ".join(s["id"] for s in row["steps"]),
                row["label"],
                row["stop"],
            )
    else:
        if args.local_model and args.out.resolve() == (ROOT / "results").resolve():
            parser.error("真实模型请指定独立 --out 目录以保留固定响应基线")
        traces = [
            run(case, documents, policy, arm, args.local_model, digest)
            for case in cases
            for arm in ("A", "B")
        ]
        references = load(FROZEN / "reference.json")
        for row in traces:
            replay(row, by_id[row["case"]], documents, policy, digest)
            row["score"] = score(row, references[row["case"]])
        table, timing = tables(traces)
        args.out.mkdir(parents=True, exist_ok=True)
        for filename, content in [
            ("traces.jsonl", "".join(dump(t) + "\n" for t in traces)),
            ("comparison.md", table),
            ("timing.md", timing),
        ]:
            with tempfile.NamedTemporaryFile(
                "w", dir=args.out, delete=False, encoding="utf-8"
            ) as f:
                f.write(content)
            os.replace(f.name, args.out / filename)
        print(table + "\n" + timing)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        sys.exit(f"运行中止：{exc}")
