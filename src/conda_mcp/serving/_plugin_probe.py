from __future__ import annotations

import os
from contextlib import redirect_stdout

from .capabilities import plugin_fingerprint
from .discovery import discover_plugins


def main() -> None:
    with open(os.devnull, "w") as sink, redirect_stdout(sink):
        state = discover_plugins()
    print(plugin_fingerprint(*state))


if __name__ == "__main__":
    main()
