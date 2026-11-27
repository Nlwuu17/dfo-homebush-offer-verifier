"""用冻结的 2026 Homebush 资料对照两种查询策略。"""

import argparse
import json
import re
from datetime import date
from pathlib import Path

from verify_offer import ROOT, Reader, load

DATA = ROOT / "data/real_cases_2026_11_26"
OUT = ROOT / "results/bf26"
ORDER = ("商场品牌优惠页", "品牌活动条款", "商场活动传单", "品牌门店目录", "商场门店页", "商场活动页")
SPLITS = ("dev", "heldout", "all")
BUDGET = 3
YES, NO, UNKNOWN = "适用", "不适用", "证据不足"
META = {"id", "title", "source_type"}


def index(rows, key):
    result = {}
    for row in rows:
        value = row[key]
        if not value or value in result:
            raise ValueError(f"空或重复的 {key}: {value!r}")
        result[value] = row
    return result


def inputs(folder):
    cases = index(load(folder / "cases.json"), "case_id")
    docs = index(load(folder / "sources.json"), "id")
    for case in cases.values():
        catalogue = index(case["catalogue"], "id")
        if not catalogue:
            raise ValueError(f"{case['case_id']} 的候选目录为空")
        for key, row in catalogue.items():
            if (
                key not in docs
                or set(row) != META
                or row["source_type"] not in ORDER
                or any(row[k] != docs[key][k] for k in META)
            ):
                raise ValueError(f"{case['case_id']} 的目录记录 {key} 引用或元数据不符")
    return cases, docs


def period(text, case, doc):
    """The explicit validity period a passage states, as (start, end), or None.

    None covers a missing date, a malformed one (end before start) and an
    offer with only a start date: none of these is an explicit period, so
    rule A cannot use it.
    """
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    year = re.search(r"\b(20\d{2})\b", doc["title"])
    found = None
    if len(dates) == 2:
        found = date.fromisoformat(dates[0]), date.fromisoformat(dates[1])
    elif len(dates) == 1 and re.search(r"仅限 ?\d{4}-\d{2}-\d{2} ?一天", text):
        found = (date.fromisoformat(dates[0]),) * 2
    elif year and (m := re.search(r"有效期 ?(\d{1,2})/(\d{1,2}) ?[–-] ?(\d{1,2})/(\d{1,2})", text)):
        # The flyer prints month/day.
        sm, sd, em, ed = map(int, m.groups())
        try:
            found = date(int(year[1]), sm, sd), date(int(year[1]), em, ed)
        except ValueError:
            return None
    elif year and (m := re.search(r"(\d+) 月 (\d+)[–-](\d+) 日", text)):
        month, start, end = map(int, m.groups())
        found = date(int(year[1]), month, start), date(int(year[1]), month, end)
    if found is None or found[0] > found[1]:
        return None
    return found


def current(text, case, doc):
    """True or False for an explicit period, None when there is none."""
    day = date.fromisoformat(case["as_of_date"])
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if len(dates) == 1 and "起限时" in text:
        # An offer without an end date is only attested on its snapshot date.
        return True if dates[0] <= day.isoformat() == doc["checked_date"] else None
    found = period(text, case, doc)
    if found is None:
        return None
    return found[0] <= day <= found[1]


# Associate each qualification with its own discount, retaining the price basis.
FEATURES = {
    "全店": "全店",
    "原价": "原价",
    "除外": "除外项目",
    "会员": "会员",
    "折后价": "折后价",
    "降价商品": "已降价商品",
    "额外": "额外|再减",
    "指定": "指定款式|指定商品",
    "完整零售价": "完整零售价",
    "最高": "最高",
    "建议零售价": "建议零售价",
    "OneASICS": "OneASICS",
}


def tiers(text):
    result = {}
    for sentence in re.split(r"[；;。]", text):
        last_rate = None
        for clause in sentence.split("，"):
            rates = re.findall(r"\d+(?:\.\d+)?%", clause)
            if not rates and last_rate and "除外项目" in clause:
                result[last_rate].add("除外")
            for rate in rates:
                features = result.setdefault(rate, set())
                features.update(
                    name
                    for name, pattern in FEATURES.items()
                    if re.search(pattern, clause)
                )
                last_rate = rate
    return result


CN_DIGITS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
# Words that set the scope of an offer. 「全部款式」 means every style, so it is
# storewide; 「全部首饰」 is every item of one category.
STOREWIDE = r"全店|全场|全部款式"
SELECTED = r"指定|精选"
CATEGORIES = (
    "首饰", "身体护理", "洗手液", "蜡烛", "鞋履", "服装", "装备",
    "果茶", "奶茶", "芒果红茶", "饮品", "包袋", "配件", "Outlet 商品",
)
# 「Outlet 门店 / Outlet 全店」 restricts the store type; 「Outlet 商品」 is a
# product scope and is handled as a category.
OUTLET_STORE = r"Outlet ?(?:门店|店|全店)"
# Wording that only frames a price and never limits it. What is left before
# the price once this and every recognised word is removed is an unknown
# limit, which the user's wording must repeat (rule B).
FRAMING = (
    r"\d{4}-\d{2}-\d{2}( 至 \d{4}-\d{2}-\d{2})?",
    r"(\d+|[一两二三四五六七八九十]) ?(杯|件|支|个)",
    r"标题为|正文主文案为|正文为|列表包括|列表中|并展示|展示|当前|另外|此外|期间|黑五|活动",
    r"按原吊牌价|原吊牌价|吊牌价|按|在|购买|任选|每件|每支|每杯|每个|全部|所有|均|另付|共",
    r"再减|额外|最高|减|off|的|和|及|或|与|、|：|:|「|」|（|）|\(|\)",
)
THRESHOLD = r"\$ ?[\d,]+(?:\.\d+)? ?以[下上]|满 ?\$ ?[\d,]+"
QUANTITY = r"买 ?(?:\d+|[一两二三四五六七八九十]) ?件"


def _count(token):
    return int(token) if token.isdigit() else CN_DIGITS[token]


def _price(token):
    value = float(token.replace(",", ""))
    return f"{value:g}"


def _limits(prefix):
    """Unknown limiting words in the text before a price, after framing is removed."""
    rest = re.sub(THRESHOLD, "", prefix)
    rest = re.sub(QUANTITY + "(或以上)?", "", rest)
    for word in CATEGORIES:
        rest = rest.replace(word, "")
    selected = r"(指定|精选)(款式|商品|款)?"
    for pattern in [STOREWIDE, selected, r"任一|任意", *FEATURES.values(), *FRAMING]:
        rest = re.sub(pattern, "", rest)
    # Latin words are brand, store or event names in these summaries.
    rest = re.sub(r"[A-Za-z][A-Za-z.'’-]*|&", "", rest)
    rest = re.sub(r"[\s\d$,.%]+", "", rest)
    return {rest} if re.search(r"[\u4e00-\u9fff]", rest) else set()


def _item(key, clause, sentence, start=None):
    """One offer: its identity (key, top), scope and the conditions on it.

    Membership is read from the whole sentence, because a source often puts
    「会员登录后」 in its own clause. A threshold or a quantity applies only
    to the clause it is written in, and is kept with its value.
    """
    quals = set()
    if "会员" in sentence:
        quals.add("会员")
    for found in re.findall(THRESHOLD, clause):
        quals.add("门槛" + re.sub(r"[\s,]", "", found))
    for found in re.finditer(r"买 ?(\d+|[一两二三四五六七八九十]) ?件(或以上)?", clause):
        quals.add(f"件数{_count(found[1])}" + ("+" if found[2] else ""))
    scope = set()
    if re.search(STOREWIDE, clause):
        scope.add("全店")
    if re.search(SELECTED, clause):
        scope.add("指定")
    cats = {c for c in CATEGORIES if c in clause}
    limits = _limits(clause[:start] if start is not None else clause)
    if re.search(r"任一|任意", clause):
        # 「购买任一饮品」 means any item of the kind, not a restriction to it.
        scope.add("全店")
        cats = set()
        limits = set()
    feats = {n for n, pattern in FEATURES.items() if re.search(pattern, clause)}
    return {
        "key": key,
        "top": "最高" in clause,
        "extra": "额外" in feats,
        "scope": scope,
        "cats": cats,
        "limits": limits,
        "quals": quals,
        "text": clause,
        "feats": feats,
    }


def offer_items(text):
    """Every offer a text states, each with its scope and conditions.

    Kinds: a percentage (「30%」), buy-one-get-one (「买一送一」), a price for a
    set (「3杯共$20」) and a price per item (「单价$12」). A threshold amount
    such as 「$3,000 以下」 is a condition, not a price.
    """
    items = []
    for sentence in re.split(r"[；;。]", text):
        bogo = re.search(r"买一送一|买一赠一|购买[^。；;]{0,15}?送一", sentence)
        if bogo:
            items.append(_item("买一送一", sentence, sentence, bogo.start()))
        last = None
        for clause in sentence.split("，"):
            found = []
            for m in re.finditer(r"\d+(?:\.\d+)?%", clause):
                found.append(_item(m[0], clause, sentence, m.start()))
            bundle = re.search(
                r"(\d+|[一两二三四五六七八九十]) ?(杯|件|支|个)[^$，]*?\$ ?(\d[\d,]*(?:\.\d+)?)",
                clause,
            )
            if bundle and re.search(r"任选|共", clause):
                n, unit, price = bundle.groups()
                found.append(
                    _item(f"{_count(n)}{unit}共${_price(price)}", clause, sentence, bundle.start())
                )
            else:
                masked = re.sub(THRESHOLD, lambda m: " " * len(m[0]), clause)
                for m in re.finditer(r"\$ ?(\d[\d,]*(?:\.\d+)?)", masked):
                    found.append(_item(f"单价${_price(m[1])}", clause, sentence, m.start()))
            if not found and last and "除外项目" in clause:
                last["feats"].add("除外")
            items.extend(found)
            if found:
                last = found[-1]
    return items


def same_offer(wanted, stated):
    """Same kind and value, and the same 「最高」 and 「额外」."""
    return (
        wanted["key"] == stated["key"]
        and wanted["top"] == stated["top"]
        and wanted["extra"] == stated["extra"]
    )


def broader(wanted, stated):
    """True when the user's description claims more than the source states (rule B)."""
    if stated["quals"] - wanted["quals"]:
        return True
    if "全店" in stated["scope"]:
        return False
    if "全店" in wanted["scope"] and (stated["scope"] or stated["cats"] or stated["limits"]):
        return True
    if "指定" in stated["scope"] and "指定" not in wanted["scope"]:
        return True
    if stated["cats"] and not (wanted["cats"] and wanted["cats"] <= stated["cats"]):
        return True
    if any(word not in wanted["text"] for word in stated["limits"]):
        # An unknown limiting word: the user's wording must repeat it.
        return True
    return False


def supports(wanted_items, stated_items):
    """Match each wanted offer against what a source states.

    Returns (supported, blocked): supported maps each wanted key to the
    features of the source items that state it at least as broadly; blocked
    is True when the source states the same offer only with a narrower scope
    or an extra condition.
    """
    supported, blocked = {}, False
    for wanted in wanted_items:
        same = [s for s in stated_items if same_offer(wanted, s)]
        fit = [s for s in same if not broader(wanted, s)]
        if fit:
            supported[wanted["key"]] = set().union(*(s["feats"] for s in fit))
        elif same:
            blocked = True
    return supported, blocked


def assess(case, read):
    wanted = offer_items(case["offer"])
    required = {}
    for item in wanted:
        required.setdefault(item["key"], set()).update(item["feats"])
    local = {}
    # Sources that state the same offer only with a narrower scope or an extra
    # condition than the user's description (rule B).
    narrower = []
    local_ids, terms, excluded, outlets, alternatives, directories = (
        [],
        [],
        [],
        [],
        [],
        [],
    )
    restricted_outlet = False
    # Sources that state the same offer with an explicit period that excludes
    # the as-of date (rule A), and those whose explicit period includes it.
    expired, dated = [], []
    for doc in read:
        key, kind = doc["id"], doc["source_type"]
        brand = case["brand"].casefold()
        location = case["centre"].split()[-1].casefold()
        named = brand in doc["title"].casefold()
        if kind == "商场活动页":
            continue
        if kind == "商场活动传单":
            passages = [p for p in doc["passages"] if brand in p["locator"].casefold()]
        else:
            passages = doc["passages"] if named else []
        if not passages:
            continue
        text = " ".join(p["summary_zh"] for p in passages)
        if kind == "商场门店页":
            # A centre store page only establishes that the store exists here.
            directories.append(key)
            continue
        if kind == "品牌门店目录":
            if location in text.casefold() and brand in doc["publisher"].casefold():
                directories.append(key)
                if re.search(r"Outlet 门店分组|列为 Factory Store", text, re.I):
                    outlets.append(key)
            continue
        window = current(text, case, doc)
        if window is None:
            # No explicit period: missing, malformed or open-ended (rule E).
            continue
        outside = window is False
        if kind == "品牌活动条款":
            # Multiple passages can specify membership/program separately from the rate.
            found, blocked = supports(wanted, offer_items(text))
            for features in found.values():
                features.update(name for name in ("会员", "OneASICS") if name in text)
            if blocked and brand in doc["publisher"].casefold():
                narrower.append(key)
                continue
            if (
                brand in doc["publisher"].casefold()
                and required
                and all(
                    rate in found and needed <= found[rate]
                    for rate, needed in required.items()
                )
            ):
                if outside:
                    expired.append(key)
                    continue
                dated.append(key)
                terms.append(key)
                if "排除 Factory Outlets" in text:
                    excluded.append(key)
        elif doc["publisher"] == case["centre"]:
            stated = offer_items(text)
            found, blocked = supports(wanted, stated)
            if blocked:
                narrower.append(key)
                continue
            if not wanted or set(found) != set(required):
                if stated and not outside:
                    alternatives.append(key)
                continue
            if outside:
                expired.append(key)
                continue
            dated.append(key)
            local_ids.append(key)
            restricted_outlet |= "限定" in text and "Outlet" in text
            for rate, values in found.items():
                local.setdefault(rate, set()).update(values)
    if narrower:
        # Rule B: a source states this offer, but only more narrowly than the
        # user's description. Another source being silent does not override it.
        return (
            UNKNOWN,
            "已读资料载有同一优惠，但范围更窄或附带用户描述未提及的条件。",
            narrower + local_ids,
            "offer_details",
        )
    if expired and dated:
        # Rule F: using one source or the other changes the as-of-date answer.
        return (
            UNKNOWN,
            "同一优惠的已读资料对有效期说法不一：有的档期包含核对日，有的排除。",
            dated + expired,
            "conflict",
        )
    if expired:
        # Rule A: every explicit period that was read excludes the as-of date.
        return (
            NO,
            "已读资料写明的同一优惠档期均不包含核对日。",
            expired,
            None,
        )
    complete = bool(required) and all(
        v <= local.get(r, set()) and r in local for r, v in required.items()
    )
    if re.search(OUTLET_STORE, case["offer"]) and not restricted_outlet:
        complete = False
    negative = bool(excluded and outlets)
    if complete and negative:
        return (
            UNKNOWN,
            "已读商场优惠与品牌门店排除条款冲突。",
            local_ids + excluded + outlets,
            "conflict",
        )
    if negative:
        return (
            NO,
            "对应优惠的品牌条款排除 Outlet，门店目录确认 Homebush 属于该类别。",
            excluded + outlets,
            None,
        )
    if complete:
        return (
            YES,
            "商场在对应档期公布同一优惠，已读资料共同覆盖价格基准、适用范围及所列附加条件。",
            local_ids,
            None,
        )
    if excluded:
        return (
            UNKNOWN,
            "品牌条款排除特定店型，仍需确认目标门店类别。",
            excluded,
            "store_type",
        )
    if local_ids:
        return (
            UNKNOWN,
            "本店优惠及折扣已定位，尚缺部分价格或资格条件。",
            local_ids,
            "offer_details",
        )
    if terms:
        reason = "品牌已公布对应优惠，参与门店范围尚未明确到 Homebush。"
        if alternatives:
            reason += "商场传单列出的折扣不同。"
        if directories:
            reason += "目录只确认门店身份。"
        return UNKNOWN, reason, terms + alternatives + directories, "local_offer"
    return (
        UNKNOWN,
        "已读资料尚未建立目标门店与指定优惠之间的关系。",
        alternatives + directories,
        "offer_details",
    )


# Source types that can state the offer itself, and so can confirm it or
# contradict it. Store pages, directories and the event page cannot.
OFFER_TYPES = ("商场品牌优惠页", "品牌活动条款", "商场活动传单")
STOP_POLICIES = ("confirm", "first_verdict")


def relevant(case, unread):
    """Unread sources that may state the same offer, from catalogue metadata only.

    A flyer covers many brands, so its metadata cannot rule it out; any other
    offer source must name the brand in its title.
    """
    brand = case["brand"].casefold()
    return [
        r
        for r in unread
        if r["source_type"] in OFFER_TYPES
        and (r["source_type"] == "商场活动传单" or brand in r["title"].casefold())
    ]


def stop_after(label, read, catalogue, budget, relevant_left, confirming, policy,
               budget_word="预算用尽"):
    """The stop reason after a read, or None, and whether a check read is due.

    Policy "confirm" (the default): after the first definite verdict, read at
    most one more source that may state the same offer, if the budget allows,
    then judge all evidence again. Policy "first_verdict" stops at the first
    definite verdict; it is kept to replay runs recorded before the change.
    """
    if policy not in STOP_POLICIES:
        raise ValueError(f"未知停止策略：{policy}")
    if label != UNKNOWN:
        if policy == "first_verdict":
            return "证据充分", confirming
        if confirming:
            return "补查完成", confirming
        if read >= budget:
            return budget_word, confirming
        if not relevant_left:
            return "没有相关候选", confirming
        return None, True
    if read >= catalogue:
        return "目录已读完", confirming
    if read >= budget:
        return budget_word, confirming
    return None, confirming


def choose(unread, arm, gap):
    preferred = (
        {
            "store_type": "品牌门店目录",
            "local_offer": "商场活动传单",
            "offer_details": "商场活动传单",
        }.get(gap)
        if arm == "B"
        else None
    )
    reasons = {
        "store_type": "核对排除条款所指的门店类别",
        "local_offer": "核对本店是否发布相同优惠",
        "offer_details": "补查本店公布的折扣及附加条件",
    }
    row = min(
        unread,
        key=lambda r: (r["source_type"] != preferred, ORDER.index(r["source_type"])),
    )
    reason = reasons[gap] if preferred == row["source_type"] else "按预定来源优先级选择"
    return row["id"], reason + "：" + row["source_type"]


def run(case, docs, arm, budget=BUDGET, policy="confirm"):
    if arm not in ("A", "B") or not 1 <= budget <= BUDGET:
        raise ValueError("无效组别或预算")
    reader = Reader(case["catalogue"], docs, budget)
    read, steps, gap = [], [], None
    confirming = checking = False
    while True:
        unread = [r for r in case["catalogue"] if r["id"] not in reader.seen]
        pool = relevant(case, unread) if checking else unread
        key, reason = choose(pool, arm, gap)
        if checking:
            reason = "补查同一优惠：" + reason
            checking = False
        read.append(reader.read(key))
        label, basis, refs, gap = assess(case, read)
        if not set(refs) <= reader.seen:
            raise ValueError("判定引用未读资料")
        left = relevant(
            case, [r for r in case["catalogue"] if r["id"] not in reader.seen]
        )
        stop, due = stop_after(
            label, len(read), len(case["catalogue"]), budget, left, confirming, policy
        )
        if due and not confirming:
            confirming = checking = True
        steps.append(
            dict(
                step=len(read),
                source_id=key,
                selection_reason=reason,
                label=label,
                reason=basis,
                citations=refs,
                stop_reason=stop,
            )
        )
        if stop:
            return dict(
                case_id=case["case_id"],
                brand=case["brand"],
                arm=arm,
                query_budget=budget,
                label=label,
                reason=basis,
                citations=refs,
                query_count=len(read),
                stop_reason=stop,
                steps=steps,
            )


def select(folder, cases, split):
    """Restrict cases to one split. Folders without splits.json are all dev.

    The held-out split is only returned when asked for by name, so a default
    run can never score it by accident.
    """
    if split not in SPLITS:
        raise ValueError(f"未知划分：{split}")
    path = folder / "splits.json"
    if not path.exists():
        return {} if split == "heldout" else cases
    splits = load(path)
    if set(splits) != set(cases) or not set(splits.values()) <= {"dev", "heldout"}:
        raise ValueError("splits.json 与案例不一致或含未知划分")
    return {k: c for k, c in cases.items() if split == "all" or splits[k] == split}


def score(folder, cases, traces, labels="gold_labels.json"):
    """Pair each trace with its reference label; None marks an unlabelled case."""
    gold = index(load(folder / labels), "case_id")
    if not cases.keys() <= gold.keys():
        raise ValueError(f"标注与问题 ID 不一致：{cases.keys() - gold.keys()}")
    for key in cases:
        g = gold[key]
        refs = g["supporting_evidence_ids"]
        if g["label"] is None:
            continue
        if (
            g["label"] not in (YES, NO, UNKNOWN)
            or not refs
            or len(set(refs)) != len(refs)
            or not set(refs) <= {r["id"] for r in cases[key]["catalogue"]}
        ):
            raise ValueError(f"{key} 的参考标签或证据 ID 无效")
    return {(t["case_id"], t["arm"]): (t, gold[t["case_id"]]["label"]) for t in traces}


def report(cases, scored, title="三个真实案例的离线评测"):
    lines = [
        f"# {title}",
        "",
        "| 案例 | 品牌 | 人工标签 | A 判定 | 正确 | 查询次数 | A 引用 | B 判定 | 正确 | 查询次数 | B 引用 |",
        "|---|---|---|---|---|---:|---|---|---|---:|---|",
    ]
    for key, c in cases.items():
        row = [key, c["brand"], scored[key, "A"][1] or "未标注"]
        for arm in ("A", "B"):
            t, g = scored[key, arm]
            row.extend(
                [
                    t["label"],
                    "—" if g is None else "是" if t["label"] == g else "否",
                    str(t["query_count"]),
                    "、".join(t["citations"]) or "无",
                ]
            )
        lines.append("| " + " | ".join(row) + " |")
    lines.extend(["", "| 组 | 正确题数 | 平均查询次数 |", "|---|---|---|"])
    for arm in ("A", "B"):
        group = [scored[key, arm] for key in cases]
        n = len(group)
        labelled = [(t, g) for t, g in group if g is not None]
        queries = sum(t["query_count"] for t, _ in group)
        lines.append(
            f"| {arm} | {sum(t['label'] == g for t, g in labelled)}/{len(labelled)} | {queries}/{n} = {queries / n:.2f} |"
        )
    unlabelled = sum(scored[key, "A"][1] is None for key in cases)
    if unlabelled:
        lines.extend(
            ["", f"正确题数只统计已标注的案例；另有 {unlabelled}/{len(cases)} 个案例未标注。"]
        )
    lines.extend(["", "## 逐题查询路径", ""])
    for key in cases:
        parts = []
        for arm in ("A", "B"):
            t, _ = scored[key, arm]
            path = " → ".join(s["source_id"] for s in t["steps"])
            parts.append(f"{arm} 组 {path}（{t['stop_reason']}）")
        lines.append(f"- {key}　" + "；".join(parts))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="cmd", required=True)
    check = cmds.add_parser("check")
    check.add_argument("case_id")
    check.add_argument("--arm", choices=["A", "B"], default="B")
    ev = cmds.add_parser("eval")
    ev.add_argument("--out", type=Path, help="默认 results/bf26；其他数据集为 results/<目录名>/<划分>")
    ev.add_argument("--split", choices=SPLITS, default="dev", help="留出集必须显式指定")
    ev.add_argument("--labels", default="gold_labels.json", help="数据目录内的标签文件名")
    for sub in (check, ev):
        sub.add_argument("--data", type=Path, default=DATA, help="数据目录")
    args = parser.parse_args()
    cases, docs = inputs(args.data)
    if args.cmd == "check":
        if args.case_id not in cases:
            parser.error("未知案例 ID")
        print(
            json.dumps(
                run(cases[args.case_id], docs, args.arm), ensure_ascii=False, indent=2
            )
        )
        return
    default = args.data.resolve() == DATA.resolve()
    cases = select(args.data, cases, args.split)
    if not cases:
        parser.error("该划分没有案例")
    if args.out is None:
        args.out = OUT if default else ROOT / "results" / args.data.name / args.split
    traces = [run(case, docs, arm) for case in cases.values() for arm in ("A", "B")]
    scored = score(args.data, cases, traces, args.labels)
    title = "三个真实案例的离线评测" if default else f"{args.data.name} 离线评测（{args.split}）"
    table = report(cases, scored, title)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "comparison.md").write_text(table, encoding="utf-8")
    (args.out / "traces.jsonl").write_text(
        "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in traces),
        encoding="utf-8",
    )
    print(table, end="")


if __name__ == "__main__":
    main()
