# Contributing

Use conda-workspaces for contributor tooling only. Install the locked development environment before running tasks:

```sh
conda workspace install --locked -e default
conda task run -e default check
```

Use `conda workspace run -e ENV -- COMMAND` for an ad hoc command. Do not put `--locked` on `conda task run`.

Run artifact checks after packaging changes:

```sh
conda workspace install --locked -e build
conda task run -e build build
conda task run -e build check-dist
conda task run -e build test-wheel
conda task run -e build test-examples
```

Build docs after `conda workspace install --locked -e docs` with `conda task run -e docs docs`. Tests use temporary prefixes and real package records. Do not commit generated build output, credentials, or changes to the generated version file.

The native CI matrix runs Python 3.11 and 3.14 on Linux, macOS ARM64, and Windows. Its required coverage job combines branch and subprocess data from every native run and enforces 95%. A local run retains the same threshold and reports code that only runs on other platforms as untested. A cross-platform lockfile records dependency resolution, not native execution.

Use Humanizer before submitting commit messages, issue titles/bodies, or pull request titles/bodies. Commit messages must not mention Kilo or include generated-authorship trailers. Follow `AGENTS.md` for code and safety boundaries.
