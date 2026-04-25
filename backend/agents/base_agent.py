"""Shared message models for all Flow agents."""

from uagents import Model


class UserQuery(Model):
    text: str
    user_id: str


class AgentReply(Model):
    text: str
    user_id: str
