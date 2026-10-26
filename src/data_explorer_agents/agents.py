"""Agents that explore datasets and guide research questions."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from data_explorer_agents.prompts import DATA_EXPLORER_SYSTEM_PROMPT

type Tool = BaseTool | Callable[..., Any] | dict[str, Any]

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


def _tool_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""


def _pass_through(result: object) -> dict[str, Any]:
    """Read the MCP tool result without changing its payload."""
    if isinstance(result, tuple):
        content = result[0] if result else None
        artifact = result[1] if len(result) > 1 else None
        if isinstance(artifact, dict):
            structured = artifact.get("structured_content")
            if isinstance(structured, dict):
                return structured
        result = content
    try:
        payload = json.loads(_tool_text(result))
    except json.JSONDecodeError as exc:
        raise ExplorerError("database returned a non-object") from exc
    if not isinstance(payload, dict):
        raise ExplorerError("database returned a non-object")
    return payload


async def run_query(
    state: ExplorerState, runtime: Runtime[ExplorerContext]
) -> dict[str, Any]:
    """Run the query by calling the database MCP ``query`` tool.

    The tool result is passed through as the rows.
    """
    url = f"{runtime.context.database_url.rstrip('/')}/mcp/"
    client = MultiServerMCPClient(
        {
            "database": {
                "transport": "streamable_http",
                "url": url,
            }
        }
    )
    try:
        tools = await client.get_tools(server_name="database")
        query_tool = next((tool for tool in tools if tool.name == "query"), None)
        if query_tool is None:
            raise ExplorerError("database call failed: query tool is not available")
        result = await query_tool.ainvoke({"question": state["query"]})
    except ExplorerError:
        raise
    except Exception as exc:
        raise ExplorerError(f"database call failed: {exc}") from exc
    payload = _pass_through(result)
    return {"rows": _rows(payload.get("rows"))}


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
