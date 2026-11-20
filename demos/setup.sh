# Source only in a disposable Bash recording shell.
set -e
set +m
DEMO_REPO="$PWD"
DEMO_PYTHON="$DEMO_REPO/.conda/envs/build/bin/python"
DEMO_VERSION="$("$DEMO_PYTHON" -I -m hatchling version)"
DEMO_ROOT="$(mktemp -d /tmp/mcp-demo.XXXXXX)"
trap 'rm -rf "$DEMO_ROOT"' EXIT

# Drop inherited conda settings and client paths before loading either tool.
for name in $(compgen -e); do
    case "$name" in
        CONDA_*|_CONDA_*|KILO_*|CODEX_*|COPILOT_*|PYTHONPATH|PYTHONHOME)
            unset "$name" ;;
    esac
done
mkdir -p "$DEMO_ROOT/home" "$DEMO_ROOT/project"
export HOME="$DEMO_ROOT/home"
export USERPROFILE="$HOME"
export XDG_CONFIG_HOME="$HOME/.config"
export APPDATA="$HOME/AppData/Roaming"
export LOCALAPPDATA="$HOME/AppData/Local"
export CONDARC="$DEMO_ROOT/condarc"
printf '{}\n' > "$CONDARC"
export CONDA_PKGS_DIRS="$DEMO_ROOT/package-cache"
export CONDA_ENVS_PATH="$DEMO_ROOT/envs"
export CONDA_NOTIFY_OUTDATED_CONDA=false
export CONDA_SOLVER=libmamba
export RATTLER_CACHE_DIR="$DEMO_ROOT/rattler-cache"
unset NO_COLOR

# Keep package provenance and rendered commands free of personal paths.
mkdir -p "$DEMO_ROOT/channel/noarch"
cp "$DEMO_REPO/conda-dist/noarch/conda-mcp-$DEMO_VERSION-"*.conda \
    "$DEMO_REPO/conda-dist/noarch/example-fastmcp-server-1.0.0-"*.conda \
    "$DEMO_ROOT/channel/noarch/"
"$DEMO_PYTHON" -I -m conda index "$DEMO_ROOT/channel"
"$DEMO_PYTHON" -I -m conda create --yes --quiet --prefix "$DEMO_ROOT/tools" \
    --override-channels --strict-channel-priority \
    -c "$DEMO_ROOT/channel" -c conda-forge "conda-mcp==$DEMO_VERSION" > /dev/null
"$DEMO_PYTHON" -I -m conda create --yes --quiet --prefix "$DEMO_ROOT/servers" \
    --override-channels --strict-channel-priority \
    -c "$DEMO_ROOT/channel" -c conda-forge "example-fastmcp-server=1.0.0" "fastmcp>=3" > /dev/null

export PATH="$DEMO_ROOT/tools/bin:$PATH"
unalias conda bat 2>/dev/null || true
conda() { "$DEMO_ROOT/tools/bin/python" -I -m conda "$@"; }
bat() { command bat --color=always --paging=never --style=plain "$@"; }
export PS1='\[\e[1;38;2;67;176;42m\]$\[\e[0m\] '
cd "$DEMO_ROOT/project"
printf '\nMCP_DEMO_READY\n'
