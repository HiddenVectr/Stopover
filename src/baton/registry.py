"""Tools, prompts and instructions the MCP server exposes. Extensions add to a registry instead of editing core code.

A tool handler is called as handler(service, request, ctx, now) with the validated request dict and returns
(data, replayed). A prompt renderer is called as render(service, arguments, ctx) and returns the message text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import mcp.types as types


@dataclass
class Tool:
    name: str
    model: type
    description: str
    handler: Callable[..., tuple[Any, bool]]
    read_only: bool = False
    destructive: bool = False

    def definition(self):
        return types.Tool(name=self.name, description=self.description, inputSchema=self.model.model_json_schema(),
                          annotations=types.ToolAnnotations(readOnlyHint=self.read_only, destructiveHint=self.destructive,
                                                            idempotentHint=True, openWorldHint=False))


@dataclass
class Prompt:
    name: str
    description: str
    render: Callable[..., str]
    arguments: list[types.PromptArgument] = field(default_factory=list)

    def definition(self):
        return types.Prompt(name=self.name, description=self.description, arguments=self.arguments or None)


class Registry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}
        self.prompts: dict[str, Prompt] = {}
        self.instructions: list[str] = []

    def add_tool(self, tool: Tool, *, replace=False):
        if tool.name in self.tools and not replace:
            raise ValueError(f"Tool {tool.name} is already registered")
        self.tools[tool.name] = tool

    def add_prompt(self, prompt: Prompt, *, replace=False):
        if prompt.name in self.prompts and not replace:
            raise ValueError(f"Prompt {prompt.name} is already registered")
        self.prompts[prompt.name] = prompt

    def add_instructions(self, text: str):
        self.instructions.append(text)

    def server_instructions(self):
        return "\n\n".join(self.instructions)

    def copy(self):
        """An independent registry to extend without changing the original."""
        clone = Registry()
        clone.tools, clone.prompts, clone.instructions = dict(self.tools), dict(self.prompts), list(self.instructions)
        return clone
