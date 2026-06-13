"""Internal Auditor package.

Re-exports `root_agent` so the ADK CLI (`adk run internal_auditor`,
`adk web`) and the Vertex AI Agent Engine loader can find it without
knowing the internal module layout.
"""

from internal_auditor.agent import root_agent

__all__ = ["root_agent"]
