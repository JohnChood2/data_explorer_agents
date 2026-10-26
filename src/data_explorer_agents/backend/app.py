"""Backend.

Receives a question from the search bar and returns the AI server's result.
Interactive API docs are at ``/docs``. The OpenAPI schema is at ``/openapi.json``.
Run from the repo root:

    uv run python -m data_explorer_agents.backend.app
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

from data_explorer_agents.utils.config import config

logger = logging.getLogger(__name__)


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
        description="Services that already handled this request, in order.",
        examples=[["ui"]],
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
        examples=[["ui", "backend", "ai", "database", "ai", "backend"]],
    )


class HealthResponse(BaseModel):
    service: str = Field(description="Name of this process.", examples=["backend"])


class ErrorResponse(BaseModel):
    detail: str = Field(description="Why the request failed.")


def _path(payload: dict[str, Any], fallback: list[str]) -> list[str]:
    raw = payload.get("path", fallback)
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return [*raw, "backend"]
    return [*fallback, "backend"]


async def _ask_ai(question: str, path: list[str]) -> dict[str, Any]:
    url = f"{config.ai.url}/ask"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"question": question, "path": path})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ai call failed: {exc}") from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="ai server returned a non-object")
    return payload


app = FastAPI(
    title="Backend",
    version="0.1.0",
    description=(
        "Receives a question from the search bar. "
        "POST /search appends backend to path and forwards the question to the AI server."
    ),
)


@app.get("/health", response_model=HealthResponse, summary="Liveness check")
def health() -> HealthResponse:
    """Report that this process is the backend."""
    return HealthResponse(service="backend")


@app.post(
    "/search",
    response_model=SearchResponse,
    summary="Forward a question to the AI server",
    responses={
        502: {
            "model": ErrorResponse,
            "description": "The AI server was unreachable or returned a payload this app could not use.",
        }
    },
)
async def search(body: SearchRequest) -> SearchResponse:
    """Append ``backend`` to ``path`` and return the AI result with ``backend`` appended again."""
    path = [*body.path, "backend"]
    logger.info("search question=%r path=%s", body.question, path)
    payload = await _ask_ai(body.question, path)
    try:
        return SearchResponse.model_validate({**payload, "path": _path(payload, path)})
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="ai server returned an invalid result") from exc


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    uvicorn.run(app, host=config.backend.host, port=config.backend.port)


if __name__ == "__main__":
    main()
