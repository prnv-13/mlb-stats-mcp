"""Errors raised by the MLB data layer."""

from mcp.server.mcpserver.exceptions import ToolError


class MLBApiError(ToolError):
    """The MLB Stats API could not answer (network failure, 404, 4xx/5xx).

    Subclasses ToolError so the message reaches the model, which can then
    explain the problem or retry with different arguments.
    """
