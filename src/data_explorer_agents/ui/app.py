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
    path: list[str] = Field(
        default_factory=list,
        description="Services that already handled this request, in order. Usually empty.",
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
    path: list[str] = Field(
        description="Services that handled the question, including the return trip.",
        examples=[["ui", "backend", "ai", "database", "ai", "backend", "ui"]],
    )


class HealthResponse(BaseModel):
    service: str = Field(description="Name of this process.", examples=["ui"])


class ErrorResponse(BaseModel):
    detail: str = Field(description="Why the request failed.")


def _path(payload: dict[str, Any], fallback: list[str]) -> list[str]:
    raw = payload.get("path", fallback)
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return [*raw, "ui"]
    return [*fallback, "ui"]


async def _search_backend(question: str, path: list[str]) -> dict[str, Any]:
    url = f"{config.backend.url}/search"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"question": question, "path": path})
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
        "POST /search appends ui to path and forwards the question to the backend."
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
    """Append ``ui`` to ``path`` and return the backend result with ``ui`` appended again."""
    path = [*body.path, "ui"]
    logger.info("search question=%r path=%s", body.question, path)
    payload = await _search_backend(body.question, path)
    try:
        return SearchResponse.model_validate({**payload, "path": _path(payload, path)})
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="backend returned an invalid result") from exc


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    uvicorn.run(app, host=config.ui.host, port=config.ui.port)


if __name__ == "__main__":
    main()
