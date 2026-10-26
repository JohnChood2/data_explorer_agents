"""Search bar.

Serves the search page and forwards each question to the backend.
Interactive API docs are at ``/docs``. The OpenAPI schema is at ``/openapi.json``.
Run from the repo root:

    uv run python -m data_explorer_agents.ui.app
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError, field_validator

from data_explorer_agents.utils.config import config

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class DatasetRow(BaseModel):
    id: str = Field(description="Stable catalog id.")
    name: str = Field(description="Display name of the dataset.")
    row_count: int = Field(description="Number of rows in the dataset.")
    description: str = Field(description="What the dataset contains.")


class SearchRequest(BaseModel):
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


class SearchResponse(BaseModel):
    question: str = Field(description="Question after trimming.")
    result: str = Field(description="One sentence describing the matching rows.")
    rows: list[DatasetRow] = Field(description="Datasets that matched the question.")


class HealthResponse(BaseModel):
    service: str = Field(description="Name of this process.", examples=["ui"])


class ErrorResponse(BaseModel):
    detail: str = Field(description="Why the request failed.")


async def _search_backend(question: str) -> dict[str, Any]:
    url = f"{config.backend.url}/search"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"question": question})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"backend call failed: {exc}") from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="backend returned a non-object")
    return payload


app = FastAPI(
    title="Search bar",
    version="0.1.0",
    description=(
        "Browser page for asking a question about the catalogs. "
        "POST /search forwards the question to the backend and returns its result."
    ),
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health", response_model=HealthResponse, summary="Liveness check")
def health() -> HealthResponse:
    """Report that this process is the search bar."""
    return HealthResponse(service="ui")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post(
    "/search",
    response_model=SearchResponse,
    summary="Search the catalogs",
    responses={
        502: {
            "model": ErrorResponse,
            "description": "The backend was unreachable or returned a payload this app could not use.",
        }
    },
)
async def search(body: SearchRequest) -> SearchResponse:
    """Forward the question and return the backend result."""
    payload = await _search_backend(body.question)
    try:
        response = SearchResponse.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="backend returned an invalid result") from exc
    logger.info("search question=%r", body.question)
    return response


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    uvicorn.run(app, host=config.ui.host, port=config.ui.port)


if __name__ == "__main__":
    main()
