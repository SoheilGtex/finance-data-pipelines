from importlib.metadata import entry_points, requires, version

import fdp


def test_package_metadata_and_version_are_explicit():
    assert version("finance-data-pipelines") == fdp.__version__ == "0.2.0"
    declared = " ".join(requires("finance-data-pipelines") or []).lower()
    assert "pyyaml" in declared
    assert "pyarrow" in declared
    assert "click" in declared


def test_installed_cli_entry_point_exists():
    scripts = {entry.name: entry.value for entry in entry_points(group="console_scripts")}
    assert scripts["fdp"] == "fdp.cli:cli"
