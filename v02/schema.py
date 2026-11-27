from typing import Literal

from pydantic import BaseModel, ConfigDict

Arm = Literal["A", "B", "C"]
Label = Literal["适用", "不适用", "证据不足"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Case(Model):
    case_id: str
    brand: str
    offer: str


class Catalogue(Model):
    cases: list[Case]
    llm_available: bool
    model: str | None
    availability_reason: str | None


class RunRequest(Model):
    strategy: Arm


class Error(Model):
    detail: str


class Passage(Model):
    locator: str
    summary_zh: str
    quote: str | None = None


class Evidence(Model):
    id: str
    title: str
    url: str
    checked_date: str
    passages: list[Passage]


class Step(Model):
    step: int
    source_id: str
    selection_reason: str
    label: Label
    reason: str
    citations: list[str]
    stop_reason: str | None
    evidence: Evidence


class Tool(Model):
    name: str
    arguments: str


class Call(Model):
    number: int
    latency_ms: int
    model: str
    status: str
    tools: list[Tool]
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class Result(Model):
    case_id: str
    arm: Arm
    status: Literal["completed", "error", "unavailable"]
    label: Label | None
    reason: str
    citations: list[str]
    steps: list[Step]
    query_count: int
    stop_reason: str
    model: str | None = None
    calls: list[Call]
    model_calls: int
    latency_ms: int
    cost_usd: float | None
