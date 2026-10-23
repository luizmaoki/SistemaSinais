import json
from contextlib import contextmanager

import pytest

from app.cli import main


@pytest.mark.parametrize("command", ["import-catalog", "import-actions"])
def test_cli_never_echoes_rejected_input_or_credentials(tmp_path, monkeypatch, capsys, db, command):
    from app import cli
    from app.catalog import CatalogDocument
    from app.corporate_actions import ActionsDocument

    secret = "CLI_SECRET_MUST_NOT_APPEAR"
    payload = {"source_uri": "https://user:" + secret + "@example.com/data?api_key=" + secret}
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload))
    @contextmanager
    def transaction():
        yield db
    class SessionFactory:
        begin = staticmethod(transaction)
    monkeypatch.setattr(cli, "SessionLocal", SessionFactory)
    monkeypatch.setattr("sys.argv", ["app.cli", command, "--file", str(path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "input_value" not in captured.err
    assert "Invalid import document" in captured.err
    # The validator really does reject this payload before writing to the DB.
    validator = CatalogDocument if command == "import-catalog" else ActionsDocument
    with pytest.raises(ValueError):
        validator.model_validate(payload)


def test_cli_missing_file_has_controlled_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["app.cli", "import-catalog", "--file", str(tmp_path / "missing.json")])
    with pytest.raises(SystemExit):
        main()
    assert "Import file could not be read" in capsys.readouterr().err
