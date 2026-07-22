import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("airtable_schema_app", ROOT / "app.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def sample_tables():
    return [{"id": "tblExample", "name": "People", "fields": [
        {"id": "fldName", "name": "Name", "type": "singleLineText"},
        {"id": "fldNew", "name": "Future", "type": "newUnknownType", "options": {"newSetting": {"x": 1}}},
    ]}]


def test_missing_token_has_useful_error(monkeypatch):
    monkeypatch.delenv("AIRTABLE_ACCESS_TOKEN", raising=False)
    with pytest.raises(module.AirtableError, match="AIRTABLE_ACCESS_TOKEN"):
        module.access_token()


def test_unknown_field_is_preserved_and_workbook_is_in_memory():
    rows, _, document = module.build_export(sample_tables(), "appExample")
    assert rows["schema"][1][4] == "newUnknownType"
    assert '"newSetting"' in rows["schema"][1][6]
    assert document["schema"] == sample_tables()
    assert module.workbook_bytes(sample_tables(), "appExample").getbuffer().nbytes > 0


def test_template_resolves_outside_repo(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    response = module.app.test_client().get("/")
    assert response.status_code == 200
    assert b"Airtable Schema Exporter" in response.data


def test_invalid_base_is_controlled(monkeypatch):
    monkeypatch.setenv("AIRTABLE_ACCESS_TOKEN", "pat_test")
    with pytest.raises(module.AirtableError, match="valid Airtable base"):
        module.get_schema("not-a-base")


def test_mocked_airtable_response(monkeypatch):
    monkeypatch.setenv("AIRTABLE_ACCESS_TOKEN", "pat_test")

    class Response:
        status_code = 200
        ok = True
        def json(self):
            return {"tables": sample_tables()}

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    assert module.get_schema("appExample", session=Session()) == sample_tables()
