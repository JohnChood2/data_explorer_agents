"""AI server.

Accepts a question from the backend, asks the database for rows, and returns
a result string. This is a dummy stand-in for the data-explorer agent.
Run from the repo root:

    uv run python -m data_explorer_agents.ai.app
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = int(os.environ.get("AI_PORT", "8002"))
DATABASE_URL = os.environ.get("DATABASE_URL", "http://127.0.0.1:8003").rstrip("/")


class DatasetRow(BaseModel):
    id: str
    name: str
    row_count: int
    description: str


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    path: list[str] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped


class AskResponse(BaseModel):
    question: str
    result: str
    rows: list[DatasetRow]
    path: list[str]


def format_result(question: str, rows: Sequence[DatasetRow]) -> str:
    if not rows:
        return f"No datasets matched {question!r}."
    noun = "dataset" if len(rows) == 1 else "datasets"
    details = "; ".join(
        f"{row.name} ({row.row_count} rows): {row.description}" for row in rows
    )
    return f"Found {len(rows)} {noun} for {question!r}. {details}"


def _path(payload: dict[str, Any], fallback: list[str]) -> list[str]:
    raw = payload.get("path", fallback)
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return [*raw, "ai"]
    return [*fallback, "ai"]


async def _query_database(question: str, path: list[str]) -> dict[str, Any]:
    url = f"{DATABASE_URL}/query"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"question": question, "path": path})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"database call failed: {exc}") from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="database returned a non-object")
    return payload


app = FastAPI(title="AI server", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "ai"}


@app.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest) -> AskResponse:
    path = [*body.path, "ai"]
    logger.info("ask question=%r path=%s", body.question, path)
    payload = await _query_database(body.question, path)
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise HTTPException(status_code=502, detail="database response missing rows")
    try:
        rows = [DatasetRow.model_validate(row) for row in raw_rows]
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="database returned invalid rows") from exc
    result = format_result(body.question, rows)
    logger.info("result question=%r path=%s", body.question, _path(payload, path))
    return AskResponse(
        question=body.question,
        result=result,
        rows=rows,
        path=_path(payload, path),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
