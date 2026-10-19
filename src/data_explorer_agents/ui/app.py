"""Search bar.

Serves the search page and forwards each question to the backend.
Run from the repo root:

    uv run python -m data_explorer_agents.ui.app
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = int(os.environ.get("UI_PORT", "8000"))
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8001").rstrip("/")

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Data explorer</title>
  <style>
    :root { color-scheme: light; }
    body {
      font-family: sans-serif;
      max-width: 42rem;
      margin: 2rem auto;
      padding: 0 1rem;
      color: #111;
      background: #fff;
    }
    form { display: flex; gap: 0.5rem; }
    input { flex: 1; font: inherit; padding: 0.5rem; color: #111; background: #fff; }
    button { font: inherit; padding: 0.5rem 0.75rem; }
    #output { white-space: pre-wrap; color: #111; }
  </style>
</head>
<body>
  <h1>Data explorer</h1>
  <form id="search-form">
    <input id="question" name="question" type="search" placeholder="Ask a question" required />
    <button type="submit">Search</button>
  </form>
  <pre id="output"></pre>
  <script>
    const form = document.getElementById("search-form");
    const output = document.getElementById("output");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const question = document.getElementById("question").value;
      output.textContent = "Searching…";
      const response = await fetch("/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const body = await response.json();
      if (!response.ok) {
        output.textContent = typeof body.detail === "string" ? body.detail : JSON.stringify(body, null, 2);
        return;
      }
      const rows = (body.rows || []).map((row) => "• " + row.name + " (" + row.row_count + " rows)").join("\\n");
      output.textContent = body.result + "\\n\\n" + rows + "\\n\\npath: " + body.path.join(" → ");
    });
  </script>
</body>
</html>
"""


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
        return [*raw, "ui"]
    return [*fallback, "ui"]


async def _search_backend(question: str, path: list[str]) -> dict[str, Any]:
    url = f"{BACKEND_URL}/search"
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


app = FastAPI(title="Search bar", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "ui"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


@app.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest) -> SearchResponse:
    path = [*body.path, "ui"]
    logger.info("search question=%r path=%s", body.question, path)
    payload = await _search_backend(body.question, path)
    try:
        return SearchResponse.model_validate({**payload, "path": _path(payload, path)})
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="backend returned an invalid result") from exc


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
