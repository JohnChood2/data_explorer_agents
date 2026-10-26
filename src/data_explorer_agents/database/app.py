"""In-memory dataset service.

The catalog is available as ``POST /query`` and as an MCP tool named ``query``
at ``/mcp``. Both return the same rows.
Interactive API docs for the HTTP routes are at ``/docs``.
The OpenAPI schema is at ``/openapi.json``.
Run from the repo root:

    uv run python -m data_explorer_agents.database.app
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator

from data_explorer_agents.prompts import DATABASE_MCP_INSTRUCTIONS, QUERY_TOOL_DESCRIPTION
from data_explorer_agents.utils.config import config

logger = logging.getLogger(__name__)
_TOKEN = re.compile(r"[a-z0-9]+")
_IGNORED = frozenset(
    {
        "what",
        "which",
        "when",
        "where",
        "whose",
        "with",
        "from",
        "that",
        "this",
        "have",
        "does",
        "about",
        "into",
        "your",
        "their",
        "there",
        "these",
        "those",
        "contain",
        "contains",
        "containing",
        "dataset",
        "datasets",
        "data",
        "show",
        "list",
        "find",
        "give",
    }
)


class DatasetRow(BaseModel):
    id: str = Field(description="Stable catalog id.")
    name: str = Field(description="Display name of the dataset.")
    row_count: int = Field(description="Number of rows in the dataset.")
    description: str = Field(description="What the dataset contains.")


DATASETS: tuple[DatasetRow, ...] = (
    DatasetRow(
        id="sdss-galaxies",
        name="SDSS galaxies",
        row_count=120_000,
        description="Galaxy catalog with redshift, magnitude, and morphology.",
    ),
    DatasetRow(
        id="gaia-stars",
        name="Gaia stars",
        row_count=1_800_000_000,
        description="Stellar positions, parallax, and photometry.",
    ),
    DatasetRow(
        id="kepler-exoplanets",
        name="Kepler exoplanets",
        row_count=2_662,
        description="Confirmed exoplanets and their host-star properties.",
    ),
)


class QueryRequest(BaseModel):
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


class QueryResponse(BaseModel):
    question: str = Field(description="Question after trimming.")
    rows: list[DatasetRow] = Field(
        description=(
            "Matching datasets. A question with no content words returns every dataset. "
            "A question whose content words match nothing returns an empty list."
        )
    )


class HealthResponse(BaseModel):
    service: str = Field(description="Name of this process.", examples=["database"])


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN.findall(text.lower()) if len(token) >= 4}


def _overlaps(question_tokens: set[str], haystack: set[str]) -> bool:
    for token in question_tokens:
        stem = token[:5]
        if any(other.startswith(stem) or token.startswith(other[:5]) for other in haystack):
            return True
    return False


def matching_rows(question: str) -> list[DatasetRow]:
    """Return every row when the question has no content words."""
    tokens = _tokens(question) - _IGNORED
    if not tokens:
        return list(DATASETS)
    return [
        row
        for row in DATASETS
        if _overlaps(tokens, _tokens(f"{row.name} {row.description}"))
    ]


def execute_query(question: str) -> QueryResponse:
    """Return the rows that match the question."""
    rows = matching_rows(question)
    logger.info("query question=%r matches=%s", question, len(rows))
    return QueryResponse(question=question, rows=rows)


mcp = FastMCP(
    "database",
    instructions=DATABASE_MCP_INSTRUCTIONS,
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


@mcp.tool(name="query", description=QUERY_TOOL_DESCRIPTION)
def query_datasets(question: str) -> QueryResponse:
    return execute_query(question)


mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Database",
    version="0.1.0",
    description=(
        "In-memory catalog of three datasets. "
        "POST /query returns the rows whose name or description matches the question. "
        "The MCP server at /mcp exposes the same match as a tool named query. "
        "That tool is not part of this OpenAPI schema."
    ),
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse, summary="Liveness check")
def health() -> HealthResponse:
    """Report that this process is the database."""
    return HealthResponse(service="database")


@app.post("/query", response_model=QueryResponse, summary="Match datasets to a question")
def query(body: QueryRequest) -> QueryResponse:
    """Return the rows that match the question."""
    return execute_query(body.question)


app.mount("/mcp", mcp_app)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    uvicorn.run(app, host=config.database.host, port=config.database.port)


if __name__ == "__main__":
    main()
