"""The same strict models drive storage validation and MCP tool discovery."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, WithJsonSchema, model_validator


def _uuid(value):
    # Agents often send uppercase or non-v4 UUIDs; accept any UUID and store it canonically.
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("must be a UUID such as 3f2b6c1e-8d4a-4b7e-9c2d-1a5e6f7b8c9d") from None


def _expiry(value):
    """A UTC date ("2026-12-31", meaning the end of that day) or date-time with a timezone, normalised to
    YYYY-MM-DDTHH:MM:SSZ so stored values compare as text."""
    if not isinstance(value, str):
        raise ValueError("expires_at must be a date or date-time string")
    text = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text += "T23:59:59Z"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("expires_at must look like 2026-12-31 or 2026-12-31T17:00:00Z") from None
    if parsed.utcoffset() is None:
        raise ValueError("expires_at needs a timezone, e.g. 2026-12-31T17:00:00Z")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(value):
    return re.sub(r"\s+", "-", value.strip()) if isinstance(value, str) else value


Text = Annotated[str, StringConstraints(min_length=1, max_length=8192)]
Short = Annotated[str, StringConstraints(min_length=1, max_length=160)]
Glance = Annotated[str, StringConstraints(max_length=300)]
Slug = Annotated[str, BeforeValidator(_slug), StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,80}$")]
UUID = Annotated[str, BeforeValidator(_uuid), WithJsonSchema({"type": "string", "format": "uuid"})]
Expiry = Annotated[str, BeforeValidator(_expiry), WithJsonSchema({"type": "string", "description": "UTC date (2026-12-31) or date-time with a timezone"})]
Texts = Annotated[list[Text], Field(max_length=20)]
Positive = Annotated[int, Field(ge=1)]
Token = Annotated[str, StringConstraints(min_length=32, max_length=128)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    # One or two sentences for choosing what to resume at a glance: the work, where it stopped, the next step.
    summary: Glance = ""
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
    parent_id: UUID | None = None
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
    """Identify the original criterion by index (0-based), text, or both."""
    index: Annotated[int, Field(ge=0, le=9)] | None = None
    criterion: Text | None = None
    result: Literal["pass", "fail", "not_run"]
    evidence: Text

    @model_validator(mode="after")
    def identified(self):
        if self.index is None and self.criterion is None:
            raise ValueError("Give the criterion index (0-based) or its text")
        return self


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
    operation_id: UUID | None = None
    record: Record


class Get(Model):
    id: UUID


class ListQuery(Model):
    status: Literal["available", "claimed", "completed", "all"] = "available"
    project_key: Slug | None = None
    target_client: Short | None = None
    q: Annotated[str, StringConstraints(max_length=200)] = ""
    limit: Annotated[int, Field(ge=1, le=20)] = 20
    cursor: Annotated[str, StringConstraints(max_length=2048)] | None = None


DEFAULT_LEASE = 3600
MAX_LEASE = 86400


class Claim(Model):
    operation_id: UUID | None = None
    id: UUID
    expected_revision: Positive | None = None
    action: Literal["acquire", "renew", "release"] = "acquire"
    holder_label: Short | None = None
    lease_seconds: Annotated[int, Field(ge=60, le=MAX_LEASE)] | None = None
    claim_token: Token | None = None
    claim_generation: Positive | None = None

    @model_validator(mode="after")
    def action_fields(self):
        if self.action == "acquire":
            if not self.holder_label or self.claim_token is not None or self.claim_generation is not None:
                raise ValueError("Acquire requires holder_label and no claim credentials")
        elif not self.claim_token or self.holder_label is not None:
            raise ValueError("Renew/release require claim_token, with no holder_label")
        if self.action == "release" and self.lease_seconds is not None:
            raise ValueError("Release cannot set a lease")
        return self


class Resume(Model):
    operation_id: UUID | None = None
    id: UUID
    holder_label: Short
    lease_seconds: Annotated[int, Field(ge=60, le=MAX_LEASE)] | None = None
    expected_revision: Positive | None = None


class Complete(Model):
    operation_id: UUID | None = None
    id: UUID
    expected_revision: Positive | None = None
    claim_token: Token
    claim_generation: Positive | None = None
    completion: Completion


class Delete(Model):
    id: UUID


def _not_bool(value):
    # Lax ints accept numeric strings; booleans are almost always a mistake for revisions.
    if isinstance(value, bool):
        raise ValueError("must be an integer revision, not a boolean")
    return value


MemoryKey = Annotated[str, BeforeValidator(_slug), StringConstraints(strip_whitespace=True, to_lower=True,
    pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$")]
MemoryCategory = Literal["fact", "preference", "habit", "goal", "project_context"]
MemoryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)]
# Field before BeforeValidator: in the other order, Pydantic 2.13 emits a non-standard "ge" instead of "minimum".
Revision = Annotated[int, Field(ge=0), BeforeValidator(_not_bool)]


class MemoryEntry(Model):
    key: MemoryKey = Field(description="Stable topic key, e.g. communication.response_length. Reuse the existing key when correcting a memory.")
    expected_revision: Revision = Field(description="0 for a new key; otherwise the revision returned by stopover_memory_read (for a forgotten key, its deletion-marker revision together with recreate=true).")
    content: MemoryText
    category: MemoryCategory = "fact"
    basis: Literal["stated", "observed", "inferred"] = "stated"
    source: Source | None = Field(default=None, description="Original evidence source; defaults to the updating client. Kept unchanged when the content is unchanged.")
    evidence: Annotated[str, StringConstraints(max_length=2048)] = ""
    expires_at: Expiry | None = Field(default=None, description="When this stops being true. Set it for anything time-bound (a deadline, a temporary situation); leave it out for lasting preferences and facts. Expired memories are left out of reads.")
    recreate: bool = Field(default=False, description="Re-establish a forgotten key. Only when the user has just freshly stated this memory, never from an old copy.")


class MemoryUpdate(Model):
    operation_id: UUID | None = None
    client: Short = Field(description="Harness making this update, e.g. codex or claude-code.")
    memories: list[MemoryEntry] = Field(min_length=1, max_length=50)
    partial: bool = Field(default=False, description="Apply entries that do not conflict and report the rest as action=conflict, instead of rejecting the whole batch.")
    coverage: Coverage = Field(default_factory=Coverage)

    @model_validator(mode="after")
    def unique_bounded(self):
        if len({m.key for m in self.memories}) != len(self.memories):
            raise ValueError("Memory keys must be unique within a batch")
        for memory in self.memories:
            if memory.source is None:
                memory.source = Source(client=self.client)
        bounded_json(self.model_dump(mode="json"), 49152)
        return self


class MemoryRead(Model):
    key: MemoryKey | None = None
    category: MemoryCategory | None = None
    q: Annotated[str, StringConstraints(max_length=200)] = ""
    since_revision: Revision | None = Field(default=None, description="Return changes after this store revision, including deletion markers. Advance only after reading all pages.")
    include_deleted: bool = False
    include_expired: bool = Field(default=False, description="Also return memories whose expires_at has passed (marked expired=true).")
    limit: Annotated[int, Field(ge=1, le=50)] = 20
    cursor: Annotated[str, StringConstraints(max_length=2048)] | None = None


class MemoryForgetItem(Model):
    key: MemoryKey
    expected_revision: Annotated[int, Field(ge=1), BeforeValidator(_not_bool)] | None = None


class MemoryForget(Model):
    operation_id: UUID | None = None
    memories: list[MemoryForgetItem] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_keys(self):
        if len({m.key for m in self.memories}) != len(self.memories):
            raise ValueError("Memory keys must be unique within a batch")
        return self


class MemoryExport(MemoryRead):
    format: Literal["json", "markdown"] = "json"


INPUTS = {"stopover_save": Push, "stopover_list": ListQuery, "stopover_get": Get,
          "stopover_claim": Claim, "stopover_resume": Resume, "stopover_complete": Complete, "stopover_delete": Delete}

INPUTS.update({"stopover_memory_read": MemoryRead, "stopover_memory_update": MemoryUpdate,
               "stopover_memory_forget": MemoryForget, "stopover_memory_export": MemoryExport})
