"""Install the declaration alongside the server executable."""

import os
import shutil
from pathlib import Path

destination = (
    Path(os.environ["PREFIX"]) / "share/conda-mcp/servers/fastmcp-example.json"
)
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(Path(__file__).with_name(destination.name), destination)
