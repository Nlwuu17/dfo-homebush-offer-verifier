"""Shared document tool, evidence contract and adjudication for both arms."""

import calendar
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FROZEN = ROOT / "data/frozen"
YES, NO, WAIT, UNKNOWN = "已确认适用", "已确认不适用", "待门店确认", "未经证实"
FIELDS = ("brand", "offer", "dates", "stores", "exclusions", "context")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class Reader:
    def __init__(self, catalogue, documents, budget):
        self.allowed = {row["id"] for row in catalogue}
        self.documents = documents
        self.budget = budget
        self.seen = set()

    def read(self, key):
        if key not in self.allowed or key in self.seen or len(self.seen) >= self.budget:
            raise ValueError(f"拒绝读取 {key!r}（越界、重复或预算用尽）")
        self.seen.add(key)
        return self.documents[key]


def span(text):
    iso = re.fullmatch(r"(\d{4}-\d\d-\d\d) to (\d{4}-\d\d-\d\d)", text)
    if iso:
        return tuple(date.fromisoformat(x) for x in iso.groups())
    parts = re.fullmatch(
        r"(\d+)(?:st|nd|rd|th) (\w+) (\d{4}) - (\d+)(?:st|nd|rd|th) (\w+) (\d{4})", text
    )
    if parts:
        a, m, y, b, n, z = parts.groups()
        months = list(calendar.month_name)
        return date(int(y), months.index(m), int(a)), date(
            int(z), months.index(n), int(b)
        )
    return None


def inspect(case, doc, claims):
    if not isinstance(claims, list):
        raise ValueError("claims 必须为数组")
    citations = []
    values = {field: [] for field in FIELDS}
    for c in claims:
        field, loc, quote = (c[k] for k in ("field", "location", "quote"))
        if field not in values or not isinstance(quote, str):
            raise ValueError("无效的引文结构")
        paragraph = doc["paragraphs"].get(loc, "")
        found = bool(quote.strip()) and quote in paragraph
        citations.append(
            dict(
                **{k: c[k] for k in ("field", "location", "quote")},
                found=found,
                complete=found and quote == paragraph,
            )
        )
        # Only complete curated spans qualify for adjudication. A substring may lose a qualifier.
        if found and quote == paragraph:
            values[field].append(quote.casefold())
    same = (
        case["brand"].casefold() in values["brand"]
        and case["offer"].casefold() in values["offer"]
    )
    ranges = [
        span(c["quote"])
        for c in citations
        if c["field"] == "dates"
        and c["found"]
        and c["quote"] == doc["paragraphs"][c["location"]]
    ]
    ranges = [r for r in ranges if r]
    day = date.fromisoformat(case["day"])
    current = any(a <= day <= b for a, b in ranges)
    kind = doc["type"]
    relevant = (
        same
        and kind in {"homebush_offer", "brand_offer", "brand_terms"}
        and (not ranges or current)
    )
    store = case["centre"].casefold()
    include = (
        relevant
        and current
        and (
            kind == "homebush_offer"
            or f"participating stores: {store}" in values["stores"]
        )
    )
    exclude = (
        relevant and current and f"excluded store: {store}" in values["exclusions"]
    )
    return dict(
        id=doc["id"],
        url=doc["url"],
        checked=doc["checked"],
        type=kind,
        synthetic=doc["synthetic"],
        citations=citations,
        identity=same,
        current=current,
        relevant=relevant,
        include=include,
        exclude=exclude,
    )


def decide(evidence):
    yes = any(d["include"] for d in evidence)
    no = any(d["exclude"] for d in evidence)
    if yes and no:
        return WAIT, "官方证据冲突"
    if yes or no:
        return (YES if yes else NO), "门店与对应优惠及日期已关联"
    if any(d["relevant"] for d in evidence):
        return WAIT, "官方优惠已定位，仍缺日期或门店适用依据"
    return UNKNOWN, "未定位到目标优惠的对应官方证据"
