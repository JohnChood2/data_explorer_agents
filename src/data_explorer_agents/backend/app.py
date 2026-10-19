"""Backend.

Receives a question from the search bar and returns the AI server's result.
Run from the repo root:

    uv run python -m data_explorer_agents.backend.app
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = int(os.environ.get("BACKEND_PORT", "8001"))
AI_URL = os.environ.get("AI_URL", "http://127.0.0.1:8002").rstrip("/")


class DatasetRow(BaseModel):
    id: str
    name: str
    row_count: int
    description: str


class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    path: list[str] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped


class SearchResponse(BaseModel):
    question: str
    result: str
    rows: list[DatasetRow]
    path: list[str]


def _path(payload: dict[str, Any], fallback: list[str]) -> list[str]:
    raw = payload.get("path", fallback)
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return [*raw, "backend"]
    return [*fallback, "backend"]


async def _ask_ai(question: str, path: list[str]) -> dict[str, Any]:
    url = f"{AI_URL}/ask"
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


app = FastAPI(title="Backend", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "backend"}


@app.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest) -> SearchResponse:
    path = [*body.path, "backend"]
    logger.info("search question=%r path=%s", body.question, path)
    payload = await _ask_ai(body.question, path)
    try:
        return SearchResponse.model_validate({**payload, "path": _path(payload, path)})
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="ai server returned an invalid result") from exc


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
