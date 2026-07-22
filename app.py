import json
import os
import re
import time
import uuid
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
from flask import Flask, Response, render_template, request, send_file

PROJECT_ROOT = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"))
AIRTABLE_API = "https://api.airtable.com/v0/meta"
TIMEOUT = (5, 30)
CREDENTIAL_TTL_SECONDS = 30 * 60
credentials = {}


class AirtableError(Exception):
    """A controlled Airtable error that contains no credentials."""


def access_token(provided_token=None) -> str:
    token = (provided_token or os.environ.get("AIRTABLE_ACCESS_TOKEN", "")).strip()
    if not token:
        raise AirtableError(
            "AIRTABLE_ACCESS_TOKEN is not set. Create a personal access token with "
            "schema.bases:read access and set it before starting the app."
        )
    return token


def remember_token(token: str) -> str:
    now = time.monotonic()
    expired = [key for key, (_, created) in credentials.items()
               if now - created > CREDENTIAL_TTL_SECONDS]
    for key in expired:
        credentials.pop(key, None)
    credential_id = uuid.uuid4().hex
    credentials[credential_id] = (token, now)
    return credential_id


def token_for_credential(credential_id: str) -> str:
    record = credentials.get(credential_id)
    if not record or time.monotonic() - record[1] > CREDENTIAL_TTL_SECONDS:
        credentials.pop(credential_id, None)
        raise AirtableError("The saved credential expired. Return to the home page and load the base again.")
    return record[0]


def airtable_get(path: str, *, token=None, session=None):
    client = session or requests
    try:
        response = client.get(
            f"{AIRTABLE_API}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {access_token(token)}"},
            timeout=TIMEOUT,
        )
    except requests.Timeout as error:
        raise AirtableError("Airtable timed out. Try again shortly.") from error
    except requests.RequestException as error:
        raise AirtableError("Airtable could not be reached. Check your connection.") from error

    if response.status_code in {401, 403}:
        raise AirtableError(
            "Airtable rejected the token. Check that it is current and has schema.bases:read access."
        )
    if response.status_code == 429:
        raise AirtableError("Airtable rate-limited the request. Wait briefly and try again.")
    if not response.ok:
        raise AirtableError(f"Airtable returned HTTP {response.status_code}. Try again later.")
    try:
        payload = response.json()
    except ValueError as error:
        raise AirtableError("Airtable returned an unexpected response.") from error
    if not isinstance(payload, dict):
        raise AirtableError("Airtable returned an unexpected response.")
    return payload


def get_bases(*, token=None, session=None):
    bases = airtable_get("bases", token=token, session=session).get("bases", [])
    if not isinstance(bases, list):
        raise AirtableError("Airtable returned an unexpected bases response.")
    return bases


def get_schema(base_id: str, *, token=None, session=None):
    if not re.fullmatch(r"app[A-Za-z0-9]+", base_id):
        raise AirtableError("Choose a valid Airtable base.")
    tables = airtable_get(f"bases/{base_id}/tables", token=token, session=session).get("tables", [])
    if not isinstance(tables, list):
        raise AirtableError("Airtable returned an unexpected schema response.")
    return tables


def clean_mermaid_name(name):
    cleaned = re.sub(r"_+", "_", re.sub(r"[^a-zA-Z0-9_]", "_", str(name))).strip("_")
    cleaned = cleaned or "UNKNOWN"
    return (f"T_{cleaned}" if cleaned[0].isdigit() else cleaned).upper()


def build_export(tables, base_id):
    rows = {name: [] for name in (
        "summary", "config", "schema", "formulas", "dependencies", "relationships", "options"
    )}
    table_names = {table.get("id", ""): table.get("name", "") for table in tables}

    for table in tables:
        table_name, table_id = table.get("name", ""), table.get("id", "")
        fields = table.get("fields", []) if isinstance(table.get("fields", []), list) else []
        rows["summary"].append([table_name, table_id, len(fields)])
        for field in fields:
            field_id = field.get("id", "")
            field_name = field.get("name", "")
            field_type = field.get("type", "unknown")
            description = field.get("description", "")
            options = field.get("options") if isinstance(field.get("options"), dict) else {}
            rows["schema"].append([
                table_name, table_id, field_name, field_id, field_type, description,
                json.dumps(field, ensure_ascii=False, sort_keys=True),
            ])
            formula = options.get("formula")
            if formula:
                rows["formulas"].append([table_name, field_name, field_id, field_type, formula])
                for dependency in re.findall(r"\{([^}]+)\}", str(formula)):
                    rows["dependencies"].append([table_name, field_name, dependency])
            for setting, value in options.items():
                if setting != "choices":
                    rows["config"].append([
                        table_name, field_name, field_type, setting,
                        json.dumps(value, ensure_ascii=False, default=str),
                    ])
            linked_id = options.get("linkedTableId")
            if linked_id:
                rows["relationships"].append([
                    table_name, field_name, field_type, table_names.get(linked_id, linked_id), linked_id
                ])
            for choice in options.get("choices", []) if isinstance(options.get("choices", []), list) else []:
                rows["options"].append([
                    table_name, field_name, field_type, choice.get("name", ""),
                    choice.get("color", ""), choice.get("id", ""),
                ])

    mermaid = ["erDiagram"]
    for source, field, _, target, _ in rows["relationships"]:
        mermaid.append(f"    {clean_mermaid_name(source)} ||--o{{ {clean_mermaid_name(target)} : {clean_mermaid_name(field)}")
    document = {
        "base_id": base_id,
        "schema": tables,
        "relationships": rows["relationships"],
        "formulas": rows["formulas"],
        "dependencies": rows["dependencies"],
    }
    return rows, "\n".join(mermaid), document


def workbook_bytes(tables, base_id):
    rows, mermaid, _ = build_export(tables, base_id)
    sheets = {
        "Summary": (rows["summary"], ["Table Name", "Table ID", "Field Count"]),
        "Field Configuration": (rows["config"], ["Table Name", "Field Name", "Field Type", "Setting", "Value"]),
        "Schema": (rows["schema"], ["Table Name", "Table ID", "Field Name", "Field ID", "Field Type", "Description", "Raw Field JSON"]),
        "Formula Analysis": (rows["formulas"], ["Table Name", "Field Name", "Field ID", "Field Type", "Formula"]),
        "Formula Dependencies": (rows["dependencies"], ["Table Name", "Formula Field", "Depends On"]),
        "Relationships": (rows["relationships"], ["Source Table", "Field Name", "Field Type", "Linked Table", "Linked Table ID"]),
        "Mermaid ERD": ([[mermaid]], ["Mermaid ERD"]),
        "Field Options": (rows["options"], ["Table Name", "Field Name", "Field Type", "Option Name", "Option Color", "Option ID"]),
    }
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, (data, columns) in sheets.items():
            pd.DataFrame(data, columns=columns).to_excel(writer, sheet_name=sheet_name, index=False)
    output.seek(0)
    return output


@app.route("/", methods=["GET", "POST"])
def index():
    bases, message, credential_id = [], None, None
    if request.method == "POST":
        try:
            token = access_token(request.form.get("api_key", ""))
            bases = get_bases(token=token)
            credential_id = remember_token(token)
            message = (
                f"Found {len(bases)} base(s). Choose one below."
                if bases else "No accessible bases were found. Check the token's base access."
            )
        except AirtableError as error:
            message = str(error)
    return render_template("index.html", bases=bases, message=message,
                           credential_id=credential_id)


@app.post("/export-json")
def export_json():
    base_id = request.form.get("base_id", "").strip()
    try:
        token = token_for_credential(request.form.get("credential_id", ""))
        _, _, document = build_export(get_schema(base_id, token=token), base_id)
    except AirtableError as error:
        return render_template("index.html", bases=[], message=str(error)), 400
    return Response(json.dumps(document, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{base_id}_documentation.json"'})


@app.post("/export")
def export():
    base_id = request.form.get("base_id", "").strip()
    try:
        token = token_for_credential(request.form.get("credential_id", ""))
        output = workbook_bytes(get_schema(base_id, token=token), base_id)
    except AirtableError as error:
        return render_template("index.html", bases=[], message=str(error)), 400
    return send_file(output, as_attachment=True,
                     download_name=f"{base_id}_airtable_documentation.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
