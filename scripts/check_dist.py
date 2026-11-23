"""Validate the wheel and source distribution produced for this checkout."""

from __future__ import annotations

import email
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRES = {
    "anyio>=4.9",
    "jsonschema>=4.20",
    "mcp<3,>=2",
    "pywin32>=311;sys_platform=='win32'",
    "rich>=13",
    "tomlkit>=0.13",
}
REQUIRED_SDIST_PATHS = {
    "src/conda_mcp/schema/server-v1.json",
    "tests/conftest.py",
    "tests/fixtures/windows_launch_wrapper.py",
    "scripts/check_dist.py",
    "scripts/smoke_plugin.py",
    "scripts/test_wheel.py",
    "scripts/test_examples.py",
    "examples/fastmcp/recipe.yaml",
    "examples/node/recipe.yaml",
    "examples/remote/recipe.yaml",
    "examples/wrapper/recipe.yaml",
    "recipe/conda-cli.json",
    "THIRD_PARTY_NOTICES.md",
}
FORBIDDEN_PREFIXES = ("output/", "conda-dist/", "build/", "dist/", ".pytest_cache/")


def _single(pattern: str) -> Path:
    """Return the only matching distribution file or stop with a useful error."""
    matches = list((ROOT / "dist").glob(pattern))
    if len(matches) != 1:
        raise SystemExit(
            f"Expected exactly one {pattern!r} in dist, found {len(matches)}."
        )
    return matches[0]


@dataclass(frozen=True)
class DistributionArtifacts:
    """Validate the related wheel and source archive generated for one release."""

    wheel: Path
    sdist: Path

    def validate(self) -> None:
        """Check archive data, release metadata, and the files the source ships."""
        with zipfile.ZipFile(self.wheel) as archive:
            corrupt = archive.testzip()
            assert corrupt is None, f"Wheel CRC validation failed for {corrupt}."
            names = set(archive.namelist())

            def metadata_member(suffix: str) -> str:
                matches = [name for name in names if name.endswith(suffix)]
                assert len(matches) == 1, (
                    f"Expected one {suffix} member, found {matches}."
                )
                return matches[0]

            metadata = email.message_from_bytes(
                archive.read(metadata_member(".dist-info/METADATA"))
            )
            version = metadata["Version"]
            assert version
            assert self.wheel.name.startswith(f"conda_mcp-{version}-")
            requires = {
                requirement.replace(" ", "")
                for requirement in metadata.get_all("Requires-Dist", [])
            }
            assert metadata["Name"] == "conda-mcp"
            assert metadata["Requires-Python"] == ">=3.11"
            assert requires == REQUIRES, f"Unexpected wheel dependencies: {requires}."
            entry_points = archive.read(
                metadata_member(".dist-info/entry_points.txt")
            ).decode()
            assert "conda-mcp = conda_mcp.plugin" in entry_points
            assert "conda_mcp/schema/server-v1.json" in names
        assert self.sdist.name == f"conda_mcp-{version}.tar.gz"
        with tarfile.open(self.sdist, "r:gz") as archive:
            members = archive.getmembers()
            assert members, "Source distribution is empty."
            root = Path(members[0].name).parts[0]
            assert root == f"conda_mcp-{version}"
            assert all(
                not member.issym() and not member.islnk() for member in members
            ), "Source distribution contains a link."
            names = {
                Path(member.name).relative_to(root).as_posix() for member in members
            }
            sdist_metadata = email.message_from_bytes(
                archive.extractfile(f"{root}/PKG-INFO").read()  # type: ignore[union-attr]
            )
        assert sdist_metadata["Name"] == "conda-mcp"
        assert sdist_metadata["Version"] == version
        missing = REQUIRED_SDIST_PATHS - names
        assert not missing, (
            f"Source distribution is missing: {', '.join(sorted(missing))}"
        )
        forbidden = {name for name in names if name.startswith(FORBIDDEN_PREFIXES)}
        assert not forbidden, (
            f"Source distribution includes generated files: {sorted(forbidden)}"
        )


def main() -> None:
    """Check archive integrity, package metadata, and intended shipped files."""
    wheel = _single("conda_mcp-*.whl")
    sdist = _single("conda_mcp-*.tar.gz")
    DistributionArtifacts(wheel, sdist).validate()
    print("Distribution archives contain the expected metadata and files.")


if __name__ == "__main__":
    main()
