"""Offer identity comes from a curated URL or an exact, normalized text alias."""

import os
import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
import bf26
from v02 import agent

HERE = Path(__file__).parent
YES, NO, UNKNOWN = bf26.YES, bf26.NO, bf26.UNKNOWN


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    brand: str = Field(min_length=1, max_length=100)
    text: str = Field(default="", max_length=3000)
    url: HttpUrl | None = None
    day: date = Field(
        default_factory=lambda: datetime.now(ZoneInfo("Australia/Sydney")).date()
    )
    mode: Literal["offline", "llm"] = "offline"

    @model_validator(mode="after")
    def identity(self):
        if not self.text and not self.url:
            raise ValueError("请填写优惠文案或链接。")
        return self


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    url: HttpUrl
    checked_date: date
    locator: str
    terms: str
    quote: str
    scope: Literal["homebush_included", "homebush_excluded", "context"]
    scope_text: str
    start: date
    end: date
    test_only: bool = False

    @model_validator(mode="after")
    def dates(self):
        if self.start > self.end:
            raise ValueError("资料日期倒置")
        return self


class Offer(BaseModel):
    key: str
    brand: str
    aliases: list[str]
    sources: list[Source]


def norm(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def url_key(value):
    u = urlsplit(str(value))
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(u.query, keep_blank_values=True)
            if not k.startswith("utm_")
        ]
    )
    return urlunsplit(
        (u.scheme.lower(), u.netloc.lower(), u.path.rstrip("/"), query, "")
    )


def library(legacy, existing_docs):
    primary = {}
    supplements = {}
    ids = set(existing_docs)
    brands = {key: norm(c["brand"]) for key, c in legacy.items()}
    for kind in ("library", "supplements"):
        directory = Path(os.environ.get("DFO_CATALOGUE_DIR", HERE)) / kind
        for file in sorted(directory.glob("*.json")):
            item = Offer.model_validate_json(file.read_text(encoding="utf-8"))
            for source in item.sources:
                if source.id in ids:
                    raise ValueError(f"重复资料 ID {source.id}")
                ids.add(source.id)
            if kind == "library":
                if item.key in brands or not item.aliases or not item.sources:
                    raise ValueError("活动 ID 重复，或缺少文案及证据")
                primary[item.key] = item
                brands[item.key] = norm(item.brand)
            elif brands.get(item.key) == norm(item.brand):
                supplements.setdefault(item.key, []).extend(item.sources)
            else:
                raise ValueError("补证活动或品牌不匹配")
    return primary, supplements


def same(entry, brand, aliases, urls):
    return (
        norm(entry.brand) == norm(brand)
        and (not entry.url or url_key(entry.url) in {url_key(u) for u in urls})
        and (not entry.text or norm(entry.text) in {norm(t) for t in aliases})
    )


def document(s):
    d = s.model_dump(mode="json")
    return dict(
        **d,
        source_type="商场品牌优惠页" if s.scope != "context" else "商场活动传单",
        passages=[
            dict(
                locator=s.locator,
                summary_zh=f"{s.terms} {s.scope_text} 有效期 {s.start} 至 {s.end}。",
                quote=s.quote,
            )
        ],
    )


def curated_judge(case, read):
    day = case["as_of_date"]
    positives = []
    negatives = []
    for doc in read:
        if doc["start"] <= day <= doc["end"]:
            if doc["scope"] == "homebush_included":
                positives.append(doc["id"])
            if doc["scope"] == "homebush_excluded":
                negatives.append(doc["id"])
    refs = positives + negatives
    if positives and negatives:
        return (
            UNKNOWN,
            "对应日期的官方纳入和排除条款冲突，需门店澄清。",
            refs,
            "conflict",
        )
    if len(read) < len(case["catalogue"]):
        return UNKNOWN, "尚有同一优惠的门店或日期资料待核对。", refs, "offer_details"
    if positives:
        return (
            YES,
            "本店官方资料明确纳入该优惠，核对日期位于有效期内。",
            positives,
            None,
        )
    if negatives:
        return NO, "对应日期的官方条款明确排除 Homebush。", negatives, None
    return (
        UNKNOWN,
        "缺少在所选日期有效且明确覆盖或排除 Homebush 的同一优惠条款。",
        [d["id"] for d in read],
        "local_offer",
    )


def extended_judge(case, read):
    """Use legacy rules on original documents; new, scoped facts stay separate."""
    base = [d for d in read if "scope" not in d]
    extra = [d for d in read if "scope" in d]
    label, reason, refs, gap = bf26.assess(case, base)
    fresh_label, fresh_reason, fresh_refs, _ = curated_judge(
        {**case, "catalogue": extra}, extra
    )
    if (
        gap == "conflict"
        or (fresh_label == UNKNOWN and "冲突" in fresh_reason)
        or {label, fresh_label} == {YES, NO}
    ):
        return (
            UNKNOWN,
            "已读材料的门店参与依据存在冲突。",
            refs + fresh_refs,
            "conflict",
        )
    if fresh_label != UNKNOWN:
        return fresh_label, fresh_reason, fresh_refs, None
    return label, reason, refs, gap


def resolve(entry, attached):
    legacy, docs = bf26.inputs(bf26.DATA)
    primary, supplements = library(legacy, docs)
    matches = []
    for key, item in primary.items():
        if same(entry, item.brand, item.aliases, [s.url for s in item.sources]):
            matches.append((key, item))
    for key, case in legacy.items():
        urls = [
            docs[m["id"]]["url"]
            for m in case["catalogue"]
            if m["source_type"] in ("商场品牌优惠页", "品牌活动条款")
        ]
        if same(entry, case["brand"], [case["offer"]], urls):
            matches.append((key, None))
    if len(matches) != 1:
        if attached:
            raise ValueError("尚未确定优惠身份，无法关联补充资料。")
        return None
    key, item = matches[0]
    extras = supplements.get(key, [])
    index = {url_key(s.url): s for s in extras}
    selected = []
    for url in dict.fromkeys(map(url_key, attached)):
        if url not in index:
            raise ValueError("补证链接未登记在该优惠名下。")
        selected.append(index[url])
    choices = [{"title": s.title, "url": str(s.url)} for s in extras]
    if item is None:
        case = dict(legacy[key], as_of_date=entry.day.isoformat())
        case["question"] = (
            f"{entry.day}，{entry.brand} 的 {case['offer']} 在 DFO Homebush 适用吗？"
        )
        if not selected:
            return case, docs, bf26.assess, choices, False
        added = [document(s) for s in selected]
        case["catalogue"] = [
            {k: d[k] for k in ("id", "title", "source_type")} for d in added
        ] + case["catalogue"]
        return (
            case,
            {**docs, **{d["id"]: d for d in added}},
            extended_judge,
            choices,
            True,
        )
    sources = [document(s) for s in [*item.sources, *selected]]
    case = dict(
        case_id=key,
        brand=item.brand,
        as_of_date=entry.day.isoformat(),
        question=f"{entry.day}，{entry.brand} 的 {entry.text or item.aliases[0]} 在 DFO Homebush 适用吗？",
        catalogue=[{k: d[k] for k in ("id", "title", "source_type")} for d in sources],
    )
    return (
        case,
        {d["id"]: d for d in sources},
        curated_judge,
        choices,
        True,
    )


async def verify(entry, attached):
    resolved = resolve(entry, attached)
    model, unavailable = agent.configuration()
    if entry.mode == "llm" and unavailable:
        raise RuntimeError(unavailable)
    if resolved is None:
        return dict(
            label=UNKNOWN,
            reason="缺少与该品牌及所提交链接或完整文案相匹配的官方优惠资料。请补充具体活动页或准确条款。",
            citations=[],
            trace=[],
            snapshots=[],
            supplements=[],
            stop="未匹配",
            model=None,
            calls=[],
        )
    case, docs, judge, extras, custom = resolved
    if entry.mode == "llm":
        r = await agent.llm(case, docs, model, judge=judge, review_all=custom)
        steps = [s.model_dump(exclude={"evidence"}) for s in r.steps]
        label, reason, refs, stop = r.label, r.reason, r.citations, r.stop_reason
        calls = [c.model_dump() for c in r.calls]
        state = r.status
    elif not custom:
        r = bf26.run(case, docs, "B")
        steps, label, reason, refs, stop = (
            r[k] for k in ("steps", "label", "reason", "citations", "stop_reason")
        )
        calls = []
        state = "completed"
    else:
        reader = bf26.Reader(case["catalogue"], docs, bf26.BUDGET)
        read = []
        steps = []
        gap = None
        while len(read) < min(bf26.BUDGET, len(case["catalogue"])):
            key, why = bf26.choose(
                [r for r in case["catalogue"] if r["id"] not in reader.seen], "B", gap
            )
            read.append(reader.read(key))
            label, reason, refs, gap = judge(case, read)
            steps.append(
                dict(
                    step=len(read),
                    source_id=key,
                    selection_reason=why,
                    label=label,
                    reason=reason,
                    citations=refs,
                )
            )
        stop = "目录已读完" if len(read) == len(case["catalogue"]) else "预算用尽"
        calls = []
        state = "completed"
    seen = set()
    for step in steps:
        seen.add(step["source_id"])
        if not set(step["citations"]) <= seen:
            raise ValueError("轨迹引用未读资料")
    if not set(refs) <= seen:
        raise ValueError("结论引用未读资料")
    return dict(
        label=label,
        reason=reason,
        citations=refs,
        trace=steps,
        snapshots=[docs[s["source_id"]] for s in steps],
        supplements=extras,
        stop=stop,
        model=model if entry.mode == "llm" else None,
        calls=calls,
        status=state,
    )
