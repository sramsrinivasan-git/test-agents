"""Helper: run a one-shot inner LlmAgent and return its final text.

Shared by the specialist tools (log_analyzer, asset_inspector) so each
specialist function is just `claim sandbox → build inner agent → call
this helper → return result`.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from internal_auditor import config


async def run_inner_agent(agent: LlmAgent, prompt: str, *, user_id: str) -> str:
    """Run a single turn of `agent` with `prompt` as the user message.

    Returns whatever text the agent emits in its final response event.
    The agent's tool calls (MCP tools, in our case) happen inside this
    call.
    """
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=config.APP_NAME,
        user_id=user_id,
    )
    runner = Runner(
        app_name=config.APP_NAME,
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
