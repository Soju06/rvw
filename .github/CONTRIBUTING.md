# Contributing to rvw

Thank you for improving rvw. Keep changes focused, reviewable, and covered by the repository contracts below.

## Development setup

rvw requires Python 3.12 or newer and uses uv for dependency and command management.

```bash
uv sync --all-extras
```

Before opening or updating a pull request, run each gate as a bare command:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q -m "not live"
openspec validate --specs
```

Live tests require a real Codex CLI and credentials and are excluded from the default gate.

## OpenSpec-first changes

OpenSpec is the behavioral source of truth. Read the relevant `openspec/specs/<capability>/spec.md` and adjacent `context.md` before changing behavior, CLI contracts, schemas, policy, or release behavior. Create `openspec/changes/<slug>/` with a proposal and tasks before implementation, use regression-first tests, and keep code, tests, and specifications synchronized.

Documentation-only corrections that do not change behavior may update the main spec or context directly. Keep requirements in `spec.md`; put rationale, examples, evidence, history, and operational notes in `context.md`.

## Commit and release policy

Pull request titles and commits must use Conventional Commits because release-please derives the next version from them:

- `fix:` produces a patch release.
- `feat:` produces a minor release.
- `feat!:` or a `BREAKING CHANGE:` footer produces a major release.
- Use `chore:`, `docs:`, `test:`, `refactor:`, or another appropriate conventional type for non-release work.

Do not edit `CHANGELOG.md` manually. release-please owns changelog and version updates in its release PR.

## Pull request merge gates

A pull request is ready to merge only when:

- required CI checks are green;
- `rvw gate --target <pr> --allow-heavy-discovery` reports a clean rvw review result;
- GitHub reports the pull request as mergeable with state `CLEAN`;
- behavioral changes include and implement an OpenSpec change; and
- the pull request title follows Conventional Commits.

Do not commit credentials, `.hermes` runtime output, or `/tmp/rvw/` artifacts. Changes to the external `~/.hermes/review/` registry require explicit task scope and belong in its own versioned repository.
