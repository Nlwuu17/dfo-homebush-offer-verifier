from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from starlette.concurrency import run_in_threadpool
from v02.api import app as comparison
from v02.agent import configuration
from . import store
from .tracking import Entry, verify


@asynccontextmanager
async def lifespan(app):
    await run_in_threadpool(store.init)
    yield


app = FastAPI(title="DFO Homebush 优惠核对与追踪", version="0.3", lifespan=lifespan)


class Recheck(BaseModel):
    expected_version: int = Field(ge=1)
    evidence_url: HttpUrl | None = None


async def evaluate(entry, attached):
    try:
        return await verify(entry, attached)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/records")
def records():
    m, why = configuration()
    return dict(
        records=store.recent(),
        model=m,
        llm_available=why is None,
        availability_reason=why,
    )


@app.post("/api/records", status_code=201)
async def submit(entry: Entry):
    result = await evaluate(entry, [])
    key = await run_in_threadpool(store.create, entry.model_dump(mode="json"), result)
    return {"id": key}


@app.get("/api/records/{key}")
def record(key: UUID):
    try:
        return store.get(key)
    except KeyError as e:
        raise HTTPException(404, "记录不存在") from e


@app.post("/api/records/{key}/recheck")
async def recheck(key: UUID, body: Recheck):
    old = await run_in_threadpool(record, key)
    last = old["versions"][-1]
    if last["version"] != body.expected_version:
        raise HTTPException(409, "版本已变化，请刷新。")
    attached = list(last["attached"])
    if body.evidence_url and str(body.evidence_url) not in attached:
        attached.append(str(body.evidence_url))
    result = await evaluate(Entry.model_validate(old["submission"]), attached)
    try:
        await run_in_threadpool(
            store.append, key, body.expected_version, attached, result
        )
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return await run_in_threadpool(record, key)


app.mount("/", comparison)
