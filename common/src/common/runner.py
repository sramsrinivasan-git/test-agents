"""Run a one-shot ADK agent turn and return its final text.

Shared by every agent: specialists invoke it to run an inner LlmAgent
against a freshly claimed MCP endpoint, and HTTP entrypoints invoke it
to run the root agent for a request. Each call gets a fresh in-memory
session (one-shot, no cross-call memory).
"""

from __future__ import annotations

from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


async def run_agent(
    agent: BaseAgent,
    prompt: str,
    *,
    app_name: str,
    user_id: str,
) -> str:
    """Run a single turn of `agent` with `prompt` as the user message.

    Args:
        agent: The ADK agent to run.
        prompt: The user message text for this turn.
        app_name: ADK app name for the session (per-agent identifier).
        user_id: Caller identity for the session.

    Returns:
        The text of the agent's final response event (empty string if the
        agent emits no final text). The agent's tool calls happen inside
        this call.
    """
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
    )
    runner = Runner(
        app_name=app_name,
        agent=agent,
        session_service=session_service,
    )
    new_message = types.Content(
        role="user", parts=[types.Part.from_text(text=prompt)]
    )
    final_text = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=new_message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text or ""
    return final_text
