"""Start machine-facing stdio commands before loading conda plugins."""

from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> int:
    """Reserve protocol stdout before conda can import installed plugins."""
    protocol_stdout = os.dup(1)
    try:
        os.dup2(2, 1)

        from argparse import ArgumentParser

        from .cli.parser import configure

        parser = ArgumentParser(prog="conda-mcp-stdio")
        configure(parser)
        args = parser.parse_args(argv)
        if args.mcp_command == "serve":
            from .cli.serve import execute

            return execute(args, protocol_stdout=protocol_stdout)
        if args.mcp_command == "run":
            from .cli.run import execute

            return execute(args, protocol_stdout=protocol_stdout)
        raise ValueError("This launcher accepts only serve or run.")
    except Exception as error:  # installed conda plugins can fail during startup
        print(f"MCP launch failed: {error}", file=sys.stderr)
        return 2
    finally:
        os.close(protocol_stdout)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
