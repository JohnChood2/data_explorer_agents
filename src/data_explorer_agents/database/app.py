"""In-memory dataset service.

The AI server sends a question here and receives matching rows.
Run from the repo root:

    uv run python -m data_explorer_agents.database.app
"""

from __future__ import annotations

import logging
import os
import re

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = int(os.environ.get("DATABASE_PORT", "8003"))
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
    id: str
    name: str
    row_count: int
    description: str


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
    question: str = Field(min_length=1, max_length=500)
    path: list[str] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped


class QueryResponse(BaseModel):
    question: str
    rows: list[DatasetRow]
    path: list[str]


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


app = FastAPI(title="Database", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "database"}


@app.post("/query", response_model=QueryResponse)
def query(body: QueryRequest) -> QueryResponse:
    path = [*body.path, "database"]
    rows = matching_rows(body.question)
    logger.info("query question=%r matches=%s path=%s", body.question, len(rows), path)
    return QueryResponse(question=body.question, rows=rows, path=path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
