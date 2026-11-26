"""Sphinx configuration for conda-mcp documentation."""

from __future__ import annotations

project = html_title = "conda-mcp"
extensions = ["myst_parser", "sphinx_design"]
myst_enable_extensions = ["colon_fence"]
nitpicky = True
sd_card_legacy_separators = False
sd_tabs_storage_prefix = "conda-mcp"
html_theme = "conda_sphinx_theme"
html_theme_options = {
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/jezdez/conda-mcp",
            "icon": "fa-brands fa-square-github",
            "type": "fontawesome",
        }
    ],
    "use_edit_page_button": True,
}
html_context = {
    "github_user": "jezdez",
    "github_repo": "conda-mcp",
    "github_version": "main",
    "doc_path": "docs",
}
html_baseurl = "https://jezdez.github.io/conda-mcp/"
exclude_patterns = ["_build"]
