from __future__ import annotations

import json

from click.testing import CliRunner

from fdp.cli import cli


def test_cli_and_run_all_help():
    runner = CliRunner()
    root = runner.invoke(cli, ["--help"])
    command = runner.invoke(cli, ["run-all", "--help"])
    assert root.exit_code == 0
    assert command.exit_code == 0
    assert "run-all" in root.output
    assert "--output-dir" in command.output


def test_offline_1k_e2e_and_correctness_output(tmp_path):
    output_dir = tmp_path / "output"
    result = CliRunner().invoke(
        cli,
        [
            "run-all",
            "--source",
            "synthetic",
            "--seed",
            "20270916",
            "--rows",
            "1000",
            "--output-dir",
            str(output_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    printed = json.loads(result.output)
    correctness = json.loads((output_dir / "correctness.json").read_text(encoding="utf-8"))
    assert printed["database_final_row_count"] == 1000
    assert correctness["actual_normalized_row_count"] == 1000
    assert correctness["oracle_expected_row_count"] == 1000
    assert correctness["checksum_equal"] is True
    assert correctness["idempotent_exact_rerun"] is True
    assert correctness["integrity_check"] == "ok"
    assert correctness["missing_key_count"] == 0
    assert correctness["extra_key_count"] == 0
    assert correctness["stale_or_wrong_value_count"] == 0


def test_explicit_database_path_and_output_isolation(tmp_path, monkeypatch):
    working_dir = tmp_path / "working"
    output_dir = tmp_path / "selected-output"
    database = tmp_path / "selected-db" / "state.sqlite"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)
    result = CliRunner().invoke(
        cli,
        [
            "run-all",
            "--rows",
            "5",
            "--output-dir",
            str(output_dir),
            "--db-path",
            str(database),
        ],
    )
    assert result.exit_code == 0, result.output
    assert database.is_file()
    assert not list(working_dir.iterdir())
    assert {path.name for path in output_dir.iterdir()} == {
        "raw",
        "normalized",
        "dataset_manifest.json",
        "correctness.json",
    }


def test_config_values_are_used_and_cli_overrides_them(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("source: synthetic\nseed: 11\nrows: 7\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    result = CliRunner().invoke(
        cli,
        [
            "run-all",
            "--config",
            str(config),
            "--rows",
            "8",
            "--output-dir",
            str(output_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads((output_dir / "correctness.json").read_text(encoding="utf-8"))
    assert payload["seed"] == 11
    assert payload["requested_row_count"] == 8


def test_invalid_cli_inputs_return_nonzero(tmp_path):
    runner = CliRunner()
    cases = [
        ["run-all", "--rows", "0", "--output-dir", str(tmp_path / "zero")],
        ["run-all", "--seed", "-1", "--output-dir", str(tmp_path / "seed")],
        ["run-all", "--source", "coingecko", "--output-dir", str(tmp_path / "source")],
    ]
    for args in cases:
        result = runner.invoke(cli, args)
        assert result.exit_code != 0
        assert "Error" in result.output


def test_malformed_and_unsupported_config_return_nonzero(tmp_path):
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("rows: [", encoding="utf-8")
    unsupported = tmp_path / "unsupported.yaml"
    unsupported.write_text("rows: 5\nsecret: value\n", encoding="utf-8")
    for index, config in enumerate((malformed, unsupported)):
        result = CliRunner().invoke(
            cli,
            [
                "run-all",
                "--config",
                str(config),
                "--output-dir",
                str(tmp_path / f"output-{index}"),
            ],
        )
        assert result.exit_code != 0
        assert "Error" in result.output


def test_output_dir_is_required():
    result = CliRunner().invoke(cli, ["run-all", "--rows", "5"])
    assert result.exit_code != 0
    assert "Missing option '--output-dir'" in result.output
