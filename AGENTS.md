# xmemory-ai (Python client) — agent rules

## Always bump the version on user-facing changes

Whenever you change the library's public surface or behavior (anything under
`xmemory/`, new/changed/removed exports, bug fixes that affect callers), you
MUST bump `version` in `pyproject.toml` in the same change, following semver:

- **patch** (`0.6.1 → 0.6.2`) — backwards-compatible bug fixes only.
- **minor** (`0.6.1 → 0.7.0`) — backwards-compatible new functionality
  (new methods, new optional params, new exports).
- **major** (`0.6.1 → 1.0.0`) — breaking changes to the public API.

`xmemory/_version.py`'s `__version__` is a twin of that value and must be bumped in the same edit —
it is what the `X-Xmemory-Client` header reports, and `test_version_matches_pyproject` fails when the two
disagree. It is not derived from installed package metadata on purpose: an editable checkout keeps
serving the version recorded at install time, so a derived value would read stale for every developer
between a bump and the next `uv sync`.

Also add a matching entry to `CHANGELOG.md` under a new version heading.

Why this matters: `.github/workflows/publish.yml` refuses to publish if a git
tag `v<version>` already exists, so an un-bumped version blocks release. Each
published version must be unique.

Pure-internal changes with no caller-visible effect (tests, lint config, docs,
CI) do not require a bump.
