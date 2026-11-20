# Releasing conda-mcp

Hatchling and hatch-vcs derive the package version from Git. Release preparation does not publish anything.

## Prepare the candidate

Review the changes and prepare release notes. Create `CHANGELOG.md` before the first release. This checkout does not imply a release date. On a clean tagged checkout, hatch-vcs uses the tag as the Python package version. Do not edit the generated `src/conda_mcp/_version.py` file.

The recipe requires `CONDA_MCP_VERSION`. Local checkout builds pass the resolved Hatch version and use `SETUPTOOLS_SCM_PRETEND_VERSION` only while rattler-build copies source without Git metadata. Release builds must select the digest-verified sdist from PyPI and must not override the version stored in that archive.

## Validate

Bootstrap the contributor tooling, then install each environment from `conda.lock` before running its tasks:

```sh
conda workspace install --locked -e default
conda task run -e default check
conda workspace install --locked -e py311
conda task run -e py311 check
conda workspace install --locked -e py314
conda task run -e py314 check
conda workspace install --locked -e docs
conda task run -e docs docs
conda workspace install --locked -e build
conda task run -e build build
conda task run -e build check-dist
conda task run -e build test-wheel
conda task run -e build test-examples
conda task run -e build build-conda
conda task run -e build check-workflows
conda workspace run -e build -- python -m hatchling version
```

Before an authorized release, add a dated `## VERSION - YYYY-MM-DD` heading to `CHANGELOG.md`. On the clean release-tag checkout, confirm that Hatch prints the bare version. Do not prefix the tag with `v` or use leading zeroes. Tagging, pushing, uploading, and publication each require separate authorization.

## Publisher setup

The public repository is [jezdez/conda-mcp](https://github.com/jezdez/conda-mcp). The following external settings are required before its first release. This repository does not claim that they are configured.

- Create protected `pypi` and `anaconda` environments restricted to tags matching `*.*.*`.
- Register PyPI trusted publishing for project `conda-mcp`, owner `jezdez`, repository `conda-mcp`, workflow `.github/workflows/release.yml`, and environment `pypi`. Use PyPI's pending publisher for the first release. Do not add a PyPI token to repository secrets.
- Store a channel-scoped `ANACONDA_API_KEY` only in the protected `anaconda` environment. The reusable workflow's `publish` job declares that environment and reads its environment secret directly. It must authorize publishing under the `jezdez` owner to the `main` channel.
- Enable GitHub Actions to create releases and enable immutable GitHub releases.
- GitHub Pages is configured to use GitHub Actions. The docs workflow will deploy the strict `dirhtml` build from `main` through the `github-pages` environment after the workflow is pushed. Actions require full-SHA action pins.

GitHub artifact attestations and PyPI attestations are public evidence. They identify artifact bytes and signing identities. They do not establish package safety or grant channel authorization.

## Tag-driven publication

Push an authorized annotated tag on a commit reachable from `main`. `release.yml` calls `tests.yml` as a reusable workflow, so its native Python 3.11 and 3.14 jobs on Linux, macOS ARM64, and Windows, workflow security audit, combined branch and subprocess coverage, artifact checks, and strict docs build all finish before the release build starts.

The release checks the annotated tag and resolved Hatch version, builds exactly one wheel and sdist, validates metadata with Twine, tests the installed wheel, checks the complete gzip stream, and records the sdist SHA-256. It attests those exact files and retains the provenance bundle. The PyPI job verifies the bundle against the release workflow, commit, tag, repository, and GitHub OIDC issuer before publishing through the protected environment with PEP 740 attestations.

After PyPI succeeds, `publish-conda.yml` fetches the normalized `conda_mcp` sdist URL with bounded retries and timeouts, verifies the recorded SHA-256, and builds the noarch conda package from that source. The workflow attests and verifies the exact package and CEP 27 target-channel statement before the protected upload. The upload job downloads and repeats the verification against the same package and bundle. It refuses any existing Anaconda.org release, clears force and server overrides, and explicitly selects owner `jezdez` and channel `main`. After both package uploads succeed, the final job repeats the CEP 27 verification, attaches the exact conda artifact and bundle to the draft, then publishes it.

Publication is not atomic. If a job fails, inspect the completed jobs and both indexes before retrying. Never move a release tag, replace a published artifact, use `skip-existing`, or force an overwrite. If GitHub finalization alone fails, confirm both package publications and finalize the existing draft without rebuilding or uploading packages.
