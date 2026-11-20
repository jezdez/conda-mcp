"""Install a metadata-only wrapper declaration."""

import os
import shutil
from pathlib import Path

destination = (
    Path(os.environ["PREFIX"]) / "share/conda-mcp/servers/wrapper-example.json"
)
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(Path(__file__).with_name("wrapper-example.json"), destination)
