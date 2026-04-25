"""Per-user agent session state (in-memory; swap for Redis in prod)."""

from dataclasses import dataclass, field


@dataclass
class AgentSession:
    agent_address: str
    agent_name: str
    history: list[dict] = field(default_factory=list)  # [{"role": "user"|"agent", "text": str}]


_sessions: dict[str, AgentSession] = {}


def get_session(user_id: str) -> AgentSession | None:
    return _sessions.get(user_id)


def start_session(user_id: str, agent_address: str, agent_name: str) -> AgentSession:
    session = AgentSession(agent_address=agent_address, agent_name=agent_name)
    _sessions[user_id] = session
    return session


def end_session(user_id: str) -> None:
    _sessions.pop(user_id, None)


def append_history(user_id: str, role: str, text: str) -> None:
    session = _sessions.get(user_id)
    if session:
        session.history.append({"role": role, "text": text})
