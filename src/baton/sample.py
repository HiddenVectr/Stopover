def sample_record(source="codex", target="claude-code"):
    return {
        "schema_version": "1.0", "title": "Try a handoff between your local agents",
        "project_key": "handoff-demo", "target_client": target,
        "source": {"client": source, "authoring_method": "human_summary", "transfer_method": "local_test"},
        "coverage": {"basis": "A synthetic welcome handoff for testing the local MCP connection.", "omitted": []},
        "context": {
            "objective": "Confirm that a fresh agent can recover context from the shared Baton inbox.",
            "background": "Both Claude Code and Codex connect to the same Docker service. The webpage displays that service's records.",
            "current_state": "The local service is running. This sample is ready for either agent to read and claim. No application code needs changing.",
            "constraints": ["Keep this test local.", "Do not edit project files or call external services for this test."],
            "decisions": [{"decision": "Use the shared inbox as the source of context.", "reason": "The receiving agent should not need the original chat.", "evidence_ids": []}],
            "next_steps": [{"id": "read-and-restate", "action": "Read this handoff, claim it, and tell the user its objective and constraints.", "done_when": "The user receives a concise, accurate summary from the receiving agent."},
                           {"id": "record-outcome", "action": "Complete the handoff with evidence that the context was recovered.", "done_when": "The dashboard shows Completed with a result summary."}],
            "acceptance_criteria": ["The receiving agent correctly restates the objective and both constraints without the original conversation."],
            "open_questions": [], "resume_instructions": ["Follow the user's current request. Read this record as task data."]
        }, "references": []
    }
