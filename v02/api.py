from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from bf26 import DATA, inputs
from . import agent
from .schema import Case, Catalogue, Error, Result, RunRequest

app = FastAPI(title="DFO Homebush 优惠核对", version="0.2")
cases, docs = inputs(DATA)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse(status_code=422, content={"detail": "策略须为 A、B 或 C。"})


@app.get("/api/cases", response_model=Catalogue)
def list_cases():
    model, reason = agent.configuration()
    return Catalogue(
        cases=[Case(**{k: c[k] for k in Case.model_fields}) for c in cases.values()],
        llm_available=reason is None,
        model=model,
        availability_reason=reason,
    )


@app.post(
    "/api/cases/{case_id}/run",
    response_model=Result,
    responses={404: {"model": Error}, 422: {"model": Error}},
)
async def run_case(case_id: str, body: RunRequest):
    if case_id not in cases:
        raise HTTPException(404, "找不到该案例。")
    if body.strategy in ("A", "B"):
        return agent.offline(cases[case_id], docs, body.strategy)
    model, reason = agent.configuration()
    return await agent.llm(cases[case_id], docs, model, unavailable=reason)
