"""
FRD S1/S6: Orchestrator Agent, implemented as a LangGraph graph.

Fan-out: START -> {irctc_node, ixigo_node, confirmtkt_node} run concurrently.
Fan-in: all three -> comparison_node, which ranks the merged results.

Note on FR-6/FR-7 (booking + human-confirmation gate): that flow is
intentionally NOT modeled as a LangGraph interrupt in this build. It's
implemented instead as DB-persisted ScheduledJob status transitions plus
single-use ConfirmationToken rows (see booking_agent.py / guardrail.py).
That gives the same durability guarantee the FRD asks for (a scheduled job
survives a process restart and still requires a fresh human action to
complete) with less moving infrastructure than a LangGraph checkpointer -
worth revisiting if the graph grows more branches later.
"""
import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END

from .. import config
from ..database import SessionLocal
from .base import TrainOptionDTO
from .irctc_agent import IRCTCSearchAgent
from .ixigo_agent import IxigoSearchAgent
from .confirmtkt_agent import ConfirmTktSearchAgent
from .comparison_agent import rank_options
from . import guardrail

_AGENTS = [IRCTCSearchAgent(), IxigoSearchAgent(), ConfirmTktSearchAgent()]


def data_source_summary() -> dict:
    """
    Which adapters are returning real data and which are generating it. The UI
    needs this to label results honestly - see SearchAgent.is_live.
    """
    live = [a.platform_name for a in _AGENTS if getattr(a, "is_live", False)]
    simulated = [a.platform_name for a in _AGENTS if not getattr(a, "is_live", False)]
    return {
        "live_platforms": live,
        "simulated_platforms": simulated,
        "any_simulated": bool(simulated),
        "all_simulated": not live,
    }


def _merge_status(a: dict, b: dict) -> dict:
    return {**a, **b}


class SearchState(TypedDict):
    origin: str
    destination: str
    travel_date: str
    travel_class: str | None
    quota: str | None
    preferred_berth: str | None
    options: Annotated[list[TrainOptionDTO], operator.add]
    platform_status: Annotated[dict[str, str], _merge_status]
    ranked: list[dict]


def _make_search_node(agent):
    async def node(state: SearchState) -> dict:
        db = SessionLocal()
        try:
            guardrail.check_rate_limit(db, agent.platform_name)
        except guardrail.GuardrailRejection:
            return {"options": [], "platform_status": {agent.platform_name: "rate_limited"}}
        finally:
            db.close()

        try:
            options = await asyncio.wait_for(
                agent.search(
                    state["origin"], state["destination"], state["travel_date"],
                    state.get("travel_class"), state.get("quota"),
                ),
                timeout=config.PLATFORM_SEARCH_TIMEOUT_SECONDS,
            )
            return {"options": options, "platform_status": {agent.platform_name: "done"}}
        except asyncio.TimeoutError:
            return {"options": [], "platform_status": {agent.platform_name: "timeout"}}
        except Exception as exc:  # noqa: BLE001 - a failed platform must not fail the whole search
            return {"options": [], "platform_status": {agent.platform_name: f"failed: {exc}"}}

    return node


async def _comparison_node(state: SearchState) -> dict:
    return {"ranked": rank_options(state["options"], state.get("preferred_berth"))}


def build_graph():
    graph = StateGraph(SearchState)

    node_names = []
    for agent in _AGENTS:
        name = f"search_{agent.platform_name.lower()}"
        graph.add_node(name, _make_search_node(agent))
        node_names.append(name)

    graph.add_node("compare", _comparison_node)

    for name in node_names:
        graph.add_edge(START, name)
        graph.add_edge(name, "compare")

    graph.add_edge("compare", END)
    return graph.compile()


_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def _initial_state(origin, destination, travel_date, travel_class, quota, preferred_berth) -> SearchState:
    return {
        "origin": origin, "destination": destination, "travel_date": travel_date,
        "travel_class": travel_class, "quota": quota, "preferred_berth": preferred_berth,
        "options": [], "platform_status": {}, "ranked": [],
    }


async def run_search(
    origin: str, destination: str, travel_date: str,
    travel_class: str | None, quota: str | None, preferred_berth: str | None = None,
) -> dict:
    graph = get_graph()
    result = await graph.ainvoke(
        _initial_state(origin, destination, travel_date, travel_class, quota, preferred_berth)
    )
    return {"ranked": result["ranked"], "platform_status": result["platform_status"]}


async def stream_search(
    origin: str, destination: str, travel_date: str,
    travel_class: str | None, quota: str | None, preferred_berth: str | None = None,
):
    """
    Same search as run_search, but yields (node_name, output) as each node
    completes instead of waiting for the whole graph to finish - lets the API
    surface live per-platform status while the search is still in flight.
    """
    graph = get_graph()
    async for chunk in graph.astream(
        _initial_state(origin, destination, travel_date, travel_class, quota, preferred_berth),
        stream_mode="updates",
    ):
        for node_name, output in chunk.items():
            yield node_name, output
