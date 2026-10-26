"""AI server.

Accepts a question from the backend and runs the data explorer graph.
The graph reads the question, writes a query, calls the database MCP tool,
and returns a result string.
Interactive API docs are at ``/docs``. The OpenAPI schema is at ``/openapi.json``.
Run from the repo root:

    uv run python -m data_explorer_agents.ai.app
"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

from data_explorer_agents.agents import ExplorerContext, ExplorerError, explorer_graph
from data_explorer_agents.utils.config import config

logger = logging.getLogger(__name__)


class DatasetRow(BaseModel):
    id: str = Field(description="Stable catalog id.")
    name: str = Field(description="Display name of the dataset.")
    row_count: int = Field(description="Number of rows in the dataset.")
    description: str = Field(description="What the dataset contains.")


class AskRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=500,
        description="Natural-language question. Leading and trailing space is removed.",
        examples=["Which datasets contain galaxies?"],
    )

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped


class AskResponse(BaseModel):
    question: str = Field(description="Question after trimming.")
    result: str = Field(description="One sentence describing the matching rows.")
    rows: list[DatasetRow] = Field(description="Datasets returned by the database query tool.")


class HealthResponse(BaseModel):
    service: str = Field(description="Name of this process.", examples=["ai"])


class ErrorResponse(BaseModel):
    detail: str = Field(description="Why the request failed.")


app = FastAPI(
    title="AI server",
    version="0.1.0",
    description=(
        "Runs the data explorer graph for one question. "
        "POST /ask runs the explorer graph and returns its result sentence and rows."
    ),
)


@app.get("/health", response_model=HealthResponse, summary="Liveness check")
def health() -> HealthResponse:
    """Report that this process is the AI server."""
    return HealthResponse(service="ai")


@app.post(
    "/ask",
    response_model=AskResponse,
    summary="Answer a question with the explorer graph",
    responses={
        502: {
            "model": ErrorResponse,
            "description": "The explorer graph or the database tool failed, or the tool payload was unusable.",
        }
    },
)
async def ask(body: AskRequest) -> AskResponse:
    """Run ``explorer_graph`` and return its result sentence and rows."""
    try:
        output = await explorer_graph.ainvoke(
            {"question": body.question},
            context=ExplorerContext(database_url=config.ai.database_url),
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
    logger.info("result question=%r", body.question)
    return AskResponse(question=body.question, result=result, rows=rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    uvicorn.run(app, host=config.ai.host, port=config.ai.port)


if __name__ == "__main__":
    main()
