"""Agents that explore datasets and guide research questions."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

import httpx
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

DATA_EXPLORER_SYSTEM_PROMPT = """\
You explore datasets to help a researcher decide what is worth studying next.

Inspect structure before drawing conclusions: schemas, row counts, missingness, \
and a small sample of values. State what the data supports, what it does not, \
and which follow-up questions are still open. Prefer a short, concrete finding \
over a broad summary.
"""

type Tool = BaseTool | Callable[..., Any] | dict[str, Any]


def create_data_explorer_agent(
    model: str | BaseChatModel,
    tools: Sequence[Tool] | None = None,
    *,
    system_prompt: str = DATA_EXPLORER_SYSTEM_PROMPT,
    name: str = "data_explorer",
) -> CompiledStateGraph:
    """Build a tool-calling agent for exploring a dataset.

    ``model`` is a LangChain chat model or a provider string such as
    ``"openai:gpt-5.5"``. ``tools`` are the operations the agent may call
    while inspecting the data.
    """
    return create_agent(
        model,
        tools=list(tools) if tools else None,
        system_prompt=system_prompt,
        name=name,
    )


# Context the query-writing step will hand to a model. The stub reads these
# lists and still forwards the question, which is what the database matches on.
TABLE_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "table": "datasets",
        "columns": [
            {"name": "id", "type": "text"},
            {"name": "name", "type": "text"},
            {"name": "row_count", "type": "integer"},
            {"name": "description", "type": "text"},
        ],
    },
)

EXAMPLE_QUERIES: tuple[str, ...] = (
    "Which datasets contain galaxies?",
    "Where are the stars?",
)


class ExplorerState(TypedDict, total=False):
    question: str
    path: list[str]
    query: str
    rows: list[dict[str, Any]]
    result: str


@dataclass(frozen=True)
class ExplorerContext:
    """Run inputs that are not part of the graph state."""

    database_url: str


class ExplorerError(Exception):
    """The database call inside the graph failed."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def read_question(state: ExplorerState) -> dict[str, str]:
    """Read the question that entered the graph."""
    return {"question": state["question"]}


def question_to_query(state: ExplorerState) -> dict[str, str]:
    """Stub for the model call that turns a question into a database query.

    That call needs ``TABLE_SCHEMAS`` and ``EXAMPLE_QUERIES``. This stub checks
    that both are present and sends the question on unchanged.
    """
    if not TABLE_SCHEMAS or not EXAMPLE_QUERIES:
        raise ExplorerError("query writer is missing table schemas or examples")
    return {"query": state["question"]}


def _rows(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ExplorerError("database response missing rows")
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ExplorerError("database returned invalid rows")
        try:
            rows.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "row_count": item["row_count"],
                    "description": item["description"],
                }
            )
        except KeyError as exc:
            raise ExplorerError("database returned invalid rows") from exc
    return rows


async def run_query(
    state: ExplorerState, runtime: Runtime[ExplorerContext]
) -> dict[str, Any]:
    """Run the query by calling the database.

    This stands in for an agent calling an MCP server that runs the query.
    """
    url = f"{runtime.context.database_url.rstrip('/')}/query"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json={"question": state["query"], "path": state["path"]},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ExplorerError(f"database call failed: {exc}") from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise ExplorerError("database returned a non-object")
    raw_path = payload.get("path", state["path"])
    path = raw_path if isinstance(raw_path, list) else state["path"]
    return {"rows": _rows(payload.get("rows")), "path": path}


def analyze_data(state: ExplorerState) -> dict[str, str]:
    """Stub for the model that writes an answer from the returned rows."""
    question = state["question"]
    rows = state.get("rows", [])
    if not rows:
        return {"result": f"No datasets matched {question!r}."}
    noun = "dataset" if len(rows) == 1 else "datasets"
    details = "; ".join(
        f"{row['name']} ({row['row_count']} rows): {row['description']}" for row in rows
    )
    return {"result": f"Found {len(rows)} {noun} for {question!r}. {details}"}


def get_result(state: ExplorerState) -> dict[str, str]:
    """Return the analysis."""
    return {"result": state["result"]}


def build_explorer_graph() -> CompiledStateGraph:
    """Compile the read, query, run, analyze, and result graph."""
    graph = StateGraph(ExplorerState, context_schema=ExplorerContext)
    graph.add_node("read_question", read_question)
    graph.add_node("question_to_query", question_to_query)
    graph.add_node("run_query", run_query)
    graph.add_node("analyze_data", analyze_data)
    graph.add_node("get_result", get_result)
    graph.add_edge(START, "read_question")
    graph.add_edge("read_question", "question_to_query")
    graph.add_edge("question_to_query", "run_query")
    graph.add_edge("run_query", "analyze_data")
    graph.add_edge("analyze_data", "get_result")
    graph.add_edge("get_result", END)
    return graph.compile(name="data_explorer")


explorer_graph = build_explorer_graph()
