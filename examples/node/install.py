"""Install the Node server declaration."""

import os
import shutil
from pathlib import Path

destination = Path(os.environ["PREFIX"]) / "share/conda-mcp/servers/node-example.json"
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(Path(__file__).with_name("node-example.json"), destination)
