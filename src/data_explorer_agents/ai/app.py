"""AI server.

Accepts a question from the backend and runs the data explorer graph.
The graph reads the question, writes a query, calls the database MCP tool,
and returns a result string.
Run from the repo root:

    uv run python -m data_explorer_agents.ai.app
"""

from __future__ import annotations

import logging
import os
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

from data_explorer_agents.agents import ExplorerContext, ExplorerError, explorer_graph

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


def _path(payload: dict[str, Any], fallback: list[str]) -> list[str]:
    raw = payload.get("path", fallback)
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return [*raw, "ai"]
    return [*fallback, "ai"]


app = FastAPI(title="AI server", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "ai"}


@app.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest) -> AskResponse:
    path = [*body.path, "ai"]
    logger.info("ask question=%r path=%s", body.question, path)
    try:
        output = await explorer_graph.ainvoke(
            {"question": body.question, "path": path},
            context=ExplorerContext(database_url=DATABASE_URL),
        )
    except ExplorerError as exc:
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    raw_rows = output.get("rows")
    if not isinstance(raw_rows, list):
        raise HTTPException(status_code=502, detail="database response missing rows")
    try:
        rows = [DatasetRow.model_validate(row) for row in raw_rows]
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="database returned invalid rows") from exc
    result = output.get("result")
    if not isinstance(result, str):
        raise HTTPException(status_code=502, detail="explorer graph returned no result")
    returned_path = _path(output, path)
    logger.info("result question=%r path=%s", body.question, returned_path)
    return AskResponse(
        question=body.question,
        result=result,
        rows=rows,
        path=returned_path,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
