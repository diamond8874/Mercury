# Agent Governance & Operating Rules

## Persona & Standards
- You are a Meta-Architect Agent (or acting on behalf of one).
- Prioritize minimal file modifications unless specifically instructed to refactor.
- When generating or modifying code, preserve existing logic and docstrings where unaffected.

## Token Optimization Protocol
- Agents **MUST** read `KNOWLEDGE_GRAPH.md` before loading raw code files to identify exact targets.
- Do not perform broad, repository-wide file reads (e.g., `cat app.py`) if the specific module/function is already indexed in the Knowledge Graph. Use narrow scope reads if possible.

## Knowledge Graph & Log Maintenance Rules
- **Pre-Task Check:** Agents MUST consult `KNOWLEDGE_GRAPH.md` first to locate relevant code blocks instead of performing broad file reads.
- **Post-Task Sync:** Whenever an agent adds, edits, or deletes code in future tasks, it MUST update `KNOWLEDGE_GRAPH.md` to reflect structural changes in the same pull request/commit.
- **Log Sync:** Whenever code changes occur, agents MUST append entries to both `CHANGELOG.md` (user-facing summary) and `COMMIT_LOG.md` (agent-facing technical summary).

## Execution Safety Rules
- Do not blindly overwrite `.py` or application source code without verifying the expected behavior.
- Ensure that the execution boundaries defined in tasks are strictly adhered to.
