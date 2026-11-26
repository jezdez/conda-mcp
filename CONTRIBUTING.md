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
conda task run build
conda task run check-dist
conda task run test-wheel
conda task run test-examples
```

Tests use temporary prefixes and real package records. Do not commit generated build output, credentials, or changes to the generated version file.

The native CI matrix runs Python 3.11 and 3.14 on Linux, macOS ARM64, and Windows. Its required coverage job combines branch and subprocess data from every native run and enforces 95%. A local run retains the same threshold and reports code that only runs on other platforms as untested. A cross-platform lockfile records dependency resolution, not native execution.

Use Humanizer before submitting commit messages, issue titles/bodies, or pull request titles/bodies. Commit messages must not mention Kilo or include generated-authorship trailers. Follow `AGENTS.md` for code and configuration guidelines.

## Documentation

Organise pages by the reader's task using Diátaxis. Tutorials follow one complete path with expected results and cleanup. How-to guides address a task and its alternatives. Reference pages describe fields and options. Explanations cover the reasons behind the design. Use Humanizer when editing prose.

Use Sphinx and MyST references for pages, labelled sections, CLI options, and glossary terms so broken targets fail the build. Include maintained example files with `literalinclude` and give them filename captions. Keep essential steps visible. Use sphinx-design tabs for alternatives, numbered steps for tutorial procedures, and dropdowns for optional recordings. Builder tabs share the `builder` sync group.

Recordings need descriptive alt text and visible text equivalents. Keep their commands in sync with the VHS tapes. See [the recording instructions](demos/README.md) for setup and regeneration.

Install the locked docs environment and build the site:

```sh
conda workspace install --locked -e docs
conda task run docs
```

After changing directives or page structure, also check the text builder so the content remains readable without HTML components:

```sh
conda workspace run -e docs -- sphinx-build -W --keep-going -n -b text docs docs/_build/text
```
