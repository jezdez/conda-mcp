# Install a development build

Conda-mcp is unreleased. Build the conda package from this checkout and install it alongside the conda command you use. The guides use your `base` installation for the plugin. Packaged servers can live in separate environments.

You need a Git checkout of conda-mcp, conda 26.10 or newer, and conda-workspaces 0.12 or newer available to your `conda` command. The build downloads locked tooling and runtime packages from conda-forge. The supported workspace platforms are Linux x86-64, macOS ARM64, and Windows x86-64. Use Bash or Zsh on POSIX, or PowerShell 7 on Windows for the commands in these guides.

## Build the package

Run these commands from the repository root:

```sh
conda workspace install --locked -e build
conda task run -e build build-conda
```

The task sets the recipe version from Git and writes the package and local channel metadata under `conda-dist/`. Keep that directory available for installation.

## Install the plugin

If you have conda-cli-mcp installed, follow {doc}`migrate-from-conda-cli-mcp` first. Both packages register the same `mcp` subcommand.

From the repository root, install the artifact into `base`:

```sh
conda install -n base --override-channels -c ./conda-dist -c conda-forge conda-mcp
conda activate base
conda mcp serve --version
conda mcp list
```

The version command should print the version of your build. The inventory should include `conda-cli`, provided by the installed conda-mcp package.

The manager selects the active environment by default. Activate a server environment once, then use `conda mcp list`, `inspect`, or `register` without repeating its name. Use `-n NAME` or `-p PREFIX` to select another source explicitly.

Use {doc}`../tutorials/first-conda-session` to call conda through MCP, or {doc}`../tutorials/first-server` to connect a separately packaged server. For your usual client, {doc}`configure-serving` creates a registration with absolute launch paths.

## Test in an isolated installation

To test the development package without changing your usual conda installation, create a disposable environment instead:

```sh
conda create -n mcp-tools --override-channels -c ./conda-dist -c conda-forge conda-mcp
conda activate mcp-tools
python -I -m conda mcp serve --version
python -I -m conda mcp list
```

For this isolated setup, use `python -I -m conda` in place of `conda` while `mcp-tools` is active. The shell's `conda` function still belongs to its original installation. The explicit interpreter selects the plugin you just installed.

This alternative needs explicit interpreter selection when switching environments. The tutorials follow the `base` installation above. Activation in a terminal does not change a running GUI client's environment.

## Wheel and editable installations

A wheel can register the conda plugin when installed alongside conda, but it creates no conda package record for the built-in declaration. Consequently, `serve` can work while `list` has no `conda-cli` entry. Configure the client to launch `serve` directly in that case.

The contributor workspace installs the checkout as an editable Python package. It is useful for development, but the package-discovery tutorials require the conda artifact above. See the repository's [contributor instructions](https://github.com/jezdez/conda-mcp/blob/main/CONTRIBUTING.md) for the development tasks.

## Remove the development installation

Stop clients using the server and remove their registrations first. For the isolated installation, deactivate `mcp-tools` and remove it through your original conda:

```sh
conda deactivate
conda env remove -n mcp-tools
```

For the primary installation, remove just the plugin with `conda remove -n base conda-mcp`. Removing a package or environment does not remove its client configuration.
