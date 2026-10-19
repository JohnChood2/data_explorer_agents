"""Agents that explore datasets and guide research questions."""

from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

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

"""
1. Read the question.
2. Turn the question into a DB query. This is an LLM call.
    - Needs a list of tables and the schemas of each table.
    - Needs a list of example queries.
3. Run the query. Within that: (a) AI agent calls the MCP server, (2) query gets
run in the DB.
4. AI agent, given the data, analyzes the data. (abstract this? DeepAgents?)
5. Get the result.
"""