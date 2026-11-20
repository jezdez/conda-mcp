"""Install an endpoint declaration as a recorded package file."""

import os
import shutil
from pathlib import Path

destination = Path(os.environ["PREFIX"]) / "share/conda-mcp/servers/example.json"
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(Path(__file__).with_name("example.json"), destination)
