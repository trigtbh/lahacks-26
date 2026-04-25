"""Per-user agent session state (in-memory; swap for Redis in prod)."""

from dataclasses import dataclass, field


@dataclass
class AgentSession:
    agent_name: str
    ai_session_id: str | None = None          # Agentverse AI Engine session ID
    history: list[dict] = field(default_factory=list)


_sessions: dict[str, AgentSession] = {}


def get_session(user_id: str) -> AgentSession | None:
    return _sessions.get(user_id)


def start_session(user_id: str, agent_name: str) -> AgentSession:
    session = AgentSession(agent_name=agent_name)
    _sessions[user_id] = session
    return session


def set_ai_session(user_id: str, ai_session_id: str) -> None:
    session = _sessions.get(user_id)
    if session:
        session.ai_session_id = ai_session_id


def end_session(user_id: str) -> str | None:
    """Remove session and return the AI Engine session_id for cleanup."""
    session = _sessions.pop(user_id, None)
    return session.ai_session_id if session else None


def append_history(user_id: str, role: str, text: str) -> None:
    session = _sessions.get(user_id)
    if session:
        session.history.append({"role": role, "text": text})
