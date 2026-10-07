"""The same strict models drive storage validation and MCP tool discovery."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(min_length=1, max_length=8192)]
Short = Annotated[str, StringConstraints(min_length=1, max_length=160)]
Slug = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,80}$")]
UUID4 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")]
Texts = Annotated[list[Text], Field(max_length=20)]
Positive = Annotated[int, Field(strict=True, ge=1)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Source(Model):
    client: Short
    model: Short | None = None
    conversation_ref: Text | None = None
    captured_at: str | None = None
    authoring_method: Literal["agent_summary", "human_summary"] = "agent_summary"
    transfer_method: Literal["direct_mcp", "manual_import", "local_test"] = "direct_mcp"

    @model_validator(mode="after")
    def timestamp(self):
        if self.captured_at is not None:
            parsed = datetime.fromisoformat(self.captured_at.replace("Z", "+00:00"))
            if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
                raise ValueError("captured_at must be UTC with a timezone")
        return self


class Coverage(Model):
    basis: str = "Summary of context available to the source agent."
    omitted: Texts = Field(default_factory=list)


class Authorization(Model):
    user_request_excerpt: str = ""
    scope: str = "Follow the receiving user's current instructions."
    requires_confirmation: Texts = Field(default_factory=list)


class Decision(Model):
    decision: Text
    reason: Text
    evidence_ids: list[Slug] = Field(default_factory=list, max_length=20)


class Attempt(Model):
    action: Text
    result: Text
    verification: Literal["observed", "reported", "not_run"] = "reported"
    evidence_ids: list[Slug] = Field(default_factory=list, max_length=20)


class Fact(Model):
    text: Text
    basis: Literal["observed", "reported", "assumption"] = "reported"
    evidence_ids: list[Slug] = Field(default_factory=list, max_length=20)


class Step(Model):
    id: Slug
    action: Text
    done_when: Text


class Context(Model):
    objective: Text
    current_state: Text
    next_steps: list[Step] = Field(min_length=1, max_length=10)
    acceptance_criteria: list[Text] = Field(min_length=1, max_length=10)
    background: str = ""
    constraints: Texts = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list, max_length=20)
    attempts: list[Attempt] = Field(default_factory=list, max_length=20)
    facts: list[Fact] = Field(default_factory=list, max_length=20)
    open_questions: Texts = Field(default_factory=list)
    resume_instructions: Texts = Field(default_factory=list)


class Reference(Model):
    id: Slug
    kind: Literal["url", "file", "repository", "conversation"]
    locator: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    purpose: Text
    availability: Literal["source_only", "recipient_expected", "unknown"] = "unknown"
    excerpt: Annotated[str, StringConstraints(max_length=2048)] | None = None
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None
    observed_at: str | None = None

    @model_validator(mode="after")
    def inert_locator(self):
        value = self.locator.strip()
        if self.kind in ("url", "conversation"):
            url = urlsplit(value)
            if url.scheme.lower() not in ("http", "https") or not url.netloc or url.username or url.password:
                raise ValueError("URL references require HTTP(S) without embedded credentials")
        if value.lower().startswith(("javascript:", "data:", "vbscript:")):
            raise ValueError("Executable reference schemes are not supported")
        if self.observed_at:
            parsed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
            if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
                raise ValueError("observed_at must be UTC with a timezone")
        return self


def bounded_json(value, limit=32768):
    def walk(item, depth=0):
        if depth > 12:
            raise ValueError("JSON is too deeply nested")
        if isinstance(item, str) and len(item.encode("utf-8")) > 8192:
            raise ValueError("A text field exceeds 8 KiB")
        if isinstance(item, dict):
            for child in item.values():
                walk(child, depth + 1)
        if isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
    walk(value)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError(f"JSON exceeds {limit} bytes")
    return encoded


class Record(Model):
    schema_version: Literal["1.0"] = "1.0"
    title: Short
    source: Source
    context: Context
    project_key: Slug | None = None
    parent_id: UUID4 | None = None
    target_client: Short | None = None
    coverage: Coverage = Field(default_factory=Coverage)
    authorization: Authorization = Field(default_factory=Authorization)
    references: list[Reference] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def cross_references(self):
        refs = [r.id for r in self.references]
        if len(refs) != len(set(refs)):
            raise ValueError("Reference IDs must be unique")
        for entry in [*self.context.decisions, *self.context.attempts, *self.context.facts]:
            if any(ref not in refs for ref in entry.evidence_ids):
                raise ValueError("Evidence IDs must resolve to a reference in the record")
        steps = [s.id for s in self.context.next_steps]
        if len(steps) != len(set(steps)):
            raise ValueError("Step IDs must be unique")
        if len(self.context.acceptance_criteria) != len(set(self.context.acceptance_criteria)):
            raise ValueError("Acceptance criteria must be unique")
        bounded_json(self.model_dump(mode="json"))
        return self


class AcceptanceResult(Model):
    criterion: Text
    result: Literal["pass", "fail", "not_run"]
    evidence: Text


class Completion(Model):
    outcome: Literal["succeeded", "blocked", "abandoned"]
    summary: Text
    acceptance_results: list[AcceptanceResult] = Field(default_factory=list, max_length=10)
    artifacts: list[Reference] = Field(default_factory=list, max_length=10)
    remaining_work: Texts = Field(default_factory=list)

    @model_validator(mode="after")
    def bounded(self):
        bounded_json(self.model_dump(mode="json"), 8192)
        return self


class Push(Model):
    operation_id: UUID4
    record: Record


class Get(Model):
    id: UUID4


class ListQuery(Model):
    status: Literal["available", "claimed", "completed", "all"] = "available"
    project_key: Slug | None = None
    target_client: Short | None = None
    q: Annotated[str, StringConstraints(max_length=200)] = ""
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 20
    cursor: Annotated[str, StringConstraints(max_length=2048)] | None = None


class Claim(Model):
    operation_id: UUID4
    id: UUID4
    expected_revision: Positive
    action: Literal["acquire", "renew", "release"] = "acquire"
    holder_label: Short | None = None
    lease_seconds: Annotated[int, Field(strict=True, ge=60, le=3600)] | None = None
    claim_token: Annotated[str, StringConstraints(min_length=32, max_length=128)] | None = None
    claim_generation: Positive | None = None

    @model_validator(mode="after")
    def action_fields(self):
        if self.action == "acquire":
            if not self.holder_label or self.claim_token is not None or self.claim_generation is not None:
                raise ValueError("Acquire requires holder_label and no claim credentials")
        elif not self.claim_token or self.claim_generation is None or self.holder_label is not None:
            raise ValueError("Renew/release require claim_token and claim_generation, with no holder_label")
        if self.action == "release" and self.lease_seconds is not None:
            raise ValueError("Release cannot set a lease")
        return self


class Complete(Model):
    operation_id: UUID4
    id: UUID4
    expected_revision: Positive
    claim_token: Annotated[str, StringConstraints(min_length=32, max_length=128)]
    claim_generation: Positive
    completion: Completion


INPUTS = {"handoff_push": Push, "handoff_list": ListQuery, "handoff_get": Get,
          "handoff_claim": Claim, "handoff_complete": Complete}
