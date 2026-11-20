# conda-mcp coding guidelines

Adapted from the conda-workspaces coding guidelines.

## Project structure

- The `conda-mcp` distribution registers `conda mcp` through `conda_mcp.plugin`. Keep registration and parser configuration lightweight. Defer execution imports until dispatch.
- `cli/parser.py` configures arguments and `cli/main.py` owns dispatch, prefix selection, and conda error handling. Domain modules do not receive argparse namespaces or render terminal output.
- `servers.py` owns installed declarations, validation, and package-record discovery. Each native client has a module under `clients/`. `clients/config.py` owns shared document editing and `clients/manager.py` adapts installed servers. Keep registration writes and receipts in `registrations.py`, activation and process lifetime in `run.py`, the post-activation entry point in `_launch.py`, and native Windows process containment in `_launch_windows.py`.
- Mirror source paths in tests. Use real temporary prefixes and package records, plain pytest functions, and subprocesses with isolated homes and conda configuration.

## Imports and dependencies

- Use relative imports within the package and absolute package imports in tests and installed entry points. Keep imports at module scope except for lazy plugin callbacks, selected command dispatch, and platform-specific bindings.
- Prefer the standard library and existing dependencies. Declare minimum versions in `pyproject.toml`. Declare conda in the workspace and recipe rather than wheel metadata. Provision dependencies through `conda.toml` and regenerate `conda.lock` after workspace changes.
- Support Python 3.11 and newer. Use `from __future__ import annotations`, modern annotations, Ruff, and ty.

## Code structure and safety

- Before adding a helper, check native conda APIs and whether an existing model owns the operation. Prefer frozen dataclasses for related validated data. Split by responsibility, not by line count. Avoid section-divider comments and speculative frameworks.
- Treat unowned helper functions as technical debt. Inline trivial one-use helpers and move validation or operations onto an existing frozen model when it owns their inputs. Retain shared stateless safety or formatting helpers only when a separate function improves readability or testability. Do not create classes solely to collect functions.
- Conda owns installs, updates, removal, solving, and environment exports. Use native prefix lookup, installed records, and activation. Never create a missing environment during discovery.
- Discover only recorded manifests in the selected prefix. Bound reads, reject special files and escaping paths, and keep package ownership separate from execution trust.
- Keep configuration and execution explicit. Never contact or launch a server during discovery or registration. Keep protocol stdout separate from diagnostics and never shell-interpolate server arguments.
- Require explicit global scope for user configuration writes. Preserve unrelated entries and user policy, refuse unsafe paths, keep Kilo JSONC untouched, and store references rather than credentials. Use atomic replacement and fail closed on ambiguous receipt recovery.
- Treat metadata as literal terminal text. Administrative JSON output is one complete unstyled value. Stdio launch has no JSON envelope.

## Validation and release

- Write behavioral tests before implementation. Verify the installed entry point and lazy imports in a fresh process. Exercise manifest discovery, configuration preservation, launch behavior, and native removal with real fixtures.
- Use `conda workspace install --locked -e default` followed by `conda task run -e default check`. Use `conda workspace run -e ENV -- COMMAND` for ad hoc commands.
- Build recipe v1 artifacts with conda-build and rattler-build and verify installation outside the checkout. Report actual platform runs separately from lockfile solves. Do not claim client or protocol compatibility from static fixtures alone.
- Preserve unrelated changes. Do not commit, push, tag, or publish without explicit authorization.
- Use Humanizer for every commit message, issue title/body, and pull request title/body before submitting it. Commit messages must not reference Kilo or include Kilo authorship or generation trailers. Keep one line per paragraph or bullet in issue and pull request bodies.
