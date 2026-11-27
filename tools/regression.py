"""Regression report: the current judge against a baseline commit, on all labelled cases.

Arms A and B run in full on both the baseline checkout and the current code,
each keeping its actual path. Arm C is not re-run: its recordings are judged
again on their fixed read path with the current judge (no model calls), see
v02.cassette.rejudge. Every case lands in exactly one of four classes per arm:
right->right, wrong->right, right->wrong, wrong->wrong.

Usage, from the repository root:

    git worktree add --detach /tmp/baseline e215b10
    python3 tools/regression.py --baseline /tmp/baseline --out results/regression_v0.4
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bf26  # noqa: E402
from v02 import cassette  # noqa: E402

CANDIDATES = "data/candidates_2026_11_26"
DATASETS = [
    # (folder, labels file, cassette for arm C)
    ("data/real_cases_2026_11_26", "gold_labels.json", ["results/c_arm/cassette.jsonl"]),
    (CANDIDATES, "labels_todo.json", [
        "results/c_arm/candidates_dev.jsonl",
        "results/c_arm/candidates_heldout.jsonl",
    ]),
]
CLASSES = ("对→对", "错→对", "对→错", "错→错")


def baseline_runs(checkout, folder, labels):
    """Arm A and B traces from the baseline checkout, every case of the folder."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [sys.executable, "bf26.py", "eval", "--out", tmp]
        if folder != "data/real_cases_2026_11_26":
            cmd += ["--data", folder, "--labels", labels, "--split", "all"]
        subprocess.run(cmd, cwd=checkout, check=True, capture_output=True)
        rows = [json.loads(l) for l in open(Path(tmp) / "traces.jsonl", encoding="utf-8")]
    return {(t["case_id"], t["arm"]): t for t in rows}


def current_runs(cases, docs):
    return {(k, arm): bf26.run(c, docs, arm) for k, c in cases.items() for arm in "AB"}


def classify(gold, old, new):
    """One of the four classes, from whether the old and the new verdict are right."""
    return {
        (True, True): "对→对",
        (False, True): "错→对",
        (True, False): "对→错",
        (False, False): "错→错",
    }[(old == gold, new == gold)]


def rule_of(reason):
    """Which rule the current judge's reason comes from."""
    if "档期均不包含核对日" in reason:
        return "规则 A"
    if "有效期说法不一" in reason:
        return "规则 F"
    if "范围更窄或附带" in reason:
        return "规则 B"
    if "排除 Outlet" in reason:
        return "品牌排除条款与门店目录"
    if "公布同一优惠" in reason:
        return "同一优惠及条件均有出处"
    return "未得出结论"


def describe(item):
    parts = []
    if item["scope"]:
        parts.append("、".join(sorted(item["scope"])))
    if item["cats"]:
        parts.append("、".join(sorted(item["cats"])))
    if item["quals"]:
        parts.append("须" + "、".join(sorted(item["quals"])))
    key = ("最高 " if item["top"] else "") + item["key"]
    return key + (f"（{'；'.join(parts)}）" if parts else "")


def clauses(case, docs, refs):
    """For each cited source, the stated offer items that match the user's offer."""
    wanted = bf26.offer_items(case["offer"])
    out = []
    for key in refs:
        doc = docs[key]
        if doc["source_type"] == "商场活动传单":
            brand = case["brand"].casefold()
            text = " ".join(p["summary_zh"] for p in doc["passages"] if brand in p["locator"].casefold())
        else:
            text = " ".join(p["summary_zh"] for p in doc["passages"])
        hits = [describe(s) for s in bf26.offer_items(text) if any(bf26.same_offer(w, s) for w in wanted)]
        out.append(f"{key}：{'；'.join(hits) if hits else '门店身份或其他资料'}")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", required=True, type=Path, help="基线提交的 checkout 路径")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    here = cassette.source_revision()
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=args.baseline, check=True, capture_output=True, text=True
    ).stdout.strip()

    rows = []
    for folder, labels, cassettes in DATASETS:
        cases, docs = bf26.inputs(ROOT / folder)
        gold = {k: v["label"] for k, v in bf26.index(bf26.load(ROOT / folder / labels), "case_id").items()}
        splits = {}
        if (ROOT / folder / "splits.json").exists():
            splits = bf26.load(ROOT / folder / "splits.json")
        old = baseline_runs(args.baseline, folder, labels)
        new = current_runs(cases, docs)
        c_runs = {}
        for path in cassettes:
            for entry in cassette.load(ROOT / path):
                r = cassette.rejudge(entry, cases, docs)
                c_runs.setdefault(r["case_id"], []).append(r)
        for key, case in cases.items():
            row = {
                "case_id": key,
                "brand": case["brand"],
                "offer": case["offer"],
                "split": {"dev": "开发", "heldout": "留出"}.get(splits.get(key), "BF26"),
                "gold": gold[key],
            }
            for arm in "AB":
                o, n = old[key, arm], new[key, arm]
                row[arm] = {
                    "old": o["label"], "new": n["label"],
                    "old_path": [s["source_id"] for s in o["steps"]],
                    "new_path": [s["source_id"] for s in n["steps"]],
                    "new_reason": n["reason"], "new_citations": n["citations"],
                    "class": classify(gold[key], o["label"], n["label"]),
                }
            runs = c_runs[key]
            distinct = sorted({(tuple(r["path"]), r["recorded_label"], r["label"]) for r in runs})
            if len(distinct) != 1:
                raise SystemExit(f"{key}：C 组各次录制的路径或判定不一致，需逐次报告")
            path, rec, rej = distinct[0]
            first = runs[0]
            row["C"] = {
                "old": rec, "new": rej, "path": list(path), "runs": len(runs),
                "policy": first["recorded_policy"], "commit": (first["recorded_commit"] or "")[:7],
                "first_verdict_step": first["first_verdict_step"],
                "new_reason": first["reason"], "new_citations": first["citations"],
                "class": classify(gold[key], rec, rej),
            }
            row["triggers"] = {}
            for arm in ("A", "B", "C"):
                r = row[arm]
                if r["old"] != r["new"]:
                    row["triggers"][arm] = {
                        "rule": rule_of(r["new_reason"]),
                        "clauses": clauses(case, docs, r["new_citations"]),
                    }
            rows.append(row)

    args.out.mkdir(parents=True, exist_ok=True)
    meta = {
        "baseline_commit": base,
        "current_commit": here["commit"] if here else None,
        "current_dirty": here["dirty"] if here else None,
    }
    (args.out / "regression.json").write_text(
        json.dumps({"meta": meta, "cases": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.out / "regression.md").write_text(render(meta, rows), encoding="utf-8")
    print(render(meta, rows), end="")


def render(meta, rows):
    n = len(rows)
    lines = [
        "# v0.4 判定器回归报告",
        "",
        f"基线提交：`{meta['baseline_commit'][:7]}`；当前提交：`{(meta['current_commit'] or '未知')[:7]}`"
        + ("（工作区有未提交改动）" if meta["current_dirty"] else "") + "。",
        "",
        "覆盖 BF26 的 3 题和候选集的 20 题，共 23 题。A、B 两组在基线和当前代码上各自完整运行，保留各自的实际路径。"
        "C 组不重新调用模型：保留录制里的资料和读取顺序，只换成当前判定器重判（固定已读路径重判）。"
        "这只能说明「给它同样的证据，判定有没有改善」；当前判定器真正运行时，C 组可能提前停止，也可能继续查询。",
        "",
        "候选集的 20 题都已揭晓（其中 5 题是用过的留出集），这里只用于回归，不代表对未见优惠的表现。",
        "",
        "## 四类汇总",
        "",
        "| 组 | " + " | ".join(CLASSES) + " | 合计 | 基线正确 | 当前正确 |",
        "|---|" + "---:|" * (len(CLASSES) + 3),
    ]
    for arm, name in (("A", "A 固定组"), ("B", "B 规则策略"), ("C", "C 固定路径重判")):
        counts = [sum(r[arm]["class"] == c for r in rows) for c in CLASSES]
        old = sum(r[arm]["old"] == r["gold"] for r in rows)
        new = sum(r[arm]["new"] == r["gold"] for r in rows)
        lines.append(f"| {name} | " + " | ".join(map(str, counts)) + f" | {sum(counts)} | {old}/{n} | {new}/{n} |")
    lines += [
        "",
        "## 逐题对照",
        "",
        "| 案例 | 划分 | 冻结标签 | A 基线 → 当前 | B 基线 → 当前 | C 录制 → 重判 | C 路径 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        cells = [f"{r['case_id']} {r['brand']}", r["split"], r["gold"]]
        for arm in "AB":
            cells.append(f"{r[arm]['old']} → {r[arm]['new']}（{r[arm]['class']}）")
        c = r["C"]
        note = "；旧停止规则" if c["policy"] == "first_verdict" else ""
        cells.append(f"{c['old']} → {c['new']}（{c['class']}）")
        cells.append(" → ".join(c["path"]) + f"（{c['runs']} 次录制，`{c['commit']}`{note}）")
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## 判定变化及触发条款", ""]
    changed = [r for r in rows if r["triggers"]]
    if not changed:
        lines.append("没有判定变化。")
    for r in changed:
        lines.append(f"### {r['case_id']} {r['brand']}（{r['split']}，冻结标签「{r['gold']}」）")
        lines.append("")
        lines.append(f"用户描述：{r['offer']}")
        lines.append("")
        for arm, t in r["triggers"].items():
            x = r[arm]
            lines.append(
                f"- **{arm} 组**：{x['old']} → {x['new']}（{x['class']}）。依据：{t['rule']}。"
                + "引用：" + ("；".join(t["clauses"]) or "无") + "。"
            )
            if arm == "C" and x["first_verdict_step"]:
                lines.append(f"  当前判定器在录制路径的第 {x['first_verdict_step']} 步即可得出这一结论。")
        lines.append("")
    still = [r for r in rows if any(r[a]["class"] == "错→错" for a in "ABC")]
    lines += ["## 仍然判错的案例", ""]
    for r in still:
        arms = "、".join(a for a in "ABC" if r[a]["class"] == "错→错")
        lines.append(
            f"- {r['case_id']} {r['brand']}（{r['split']}）：冻结标签「{r['gold']}」，{arms} 组仍判「{r['A']['new'] if 'A' in arms else r['C']['new']}」。"
            f"当前判定器的理由：{r['A']['new_reason'] if 'A' in arms else r['C']['new_reason']}"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
