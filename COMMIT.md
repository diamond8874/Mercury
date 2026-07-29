# Commit Guidelines & Agent Workflow

## Commit Guidelines
This repository strictly follows Conventional Commits format:
- `feat:` A new feature
- `fix:` A bug fix
- `docs:` Documentation only changes
- `style:` Changes that do not affect the meaning of the code (white-space, formatting, etc.)
- `refactor:` A code change that neither fixes a bug nor adds a feature
- `perf:` A code change that improves performance
- `test:` Adding missing tests or correcting existing tests
- `chore:` Changes to the build process or auxiliary tools and libraries

**Example:**
`feat: add async processing for large datasets`

## Agent Commit Workflow
Automated agents operating in this repository MUST adhere to the following workflow:
1. **Branch Naming:** Create a branch for every task using the format `agent/<agent-id>/<task-type>-<short-description>`.
   - Example: `agent/meta-123/feat-add-pdf-export`
2. **Atomic Commits:** Each commit must be atomic. Do not mix unrelated changes in a single commit.
3. **Pre-commit Verification:**
   - Run relevant tests and linting before committing.
   - Update `KNOWLEDGE_GRAPH.md` if any structural codebase changes were made.
   - Update `CHANGELOG.md` and `COMMIT_LOG.md`.
4. **Staging Rules:** Stage only files related to the specific task output. Do not stage temporary files, cached outputs (`__pycache__`), or unmodified files.
