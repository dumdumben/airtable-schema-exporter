# Airtable Schema Exporter

A local Flask utility that turns an Airtable base schema into practical technical documentation. Unlike a simple field list, it produces a structured Excel workbook covering relationships, formulas, dependencies, field configuration, select options, and a Mermaid entity-relationship diagram, with a JSON export available for automation. It is intended for Airtable builders and administrators who need a portable schema inventory for auditing, handover, migration, or development.

## What the export contains

The Excel workbook separates the schema into focused worksheets:

- **Summary** — every table, its Airtable ID, and its field count.
- **Schema** — table and field names, IDs, types, descriptions, and the complete raw field definition. Keeping the raw JSON means newly introduced or unknown Airtable field types are not silently lost.
- **Field Configuration** — field settings such as formatting, linked-record behaviour, formulas, and other type-specific options.
- **Relationships** — linked-record fields mapped from their source table to the linked table, including Airtable IDs.
- **Mermaid ERD** — a ready-to-copy Mermaid `erDiagram` representation of the linked-table relationships.
- **Formula Analysis** — formula fields and their complete formula expressions.
- **Formula Dependencies** — field references extracted from formulas to make dependencies easier to review.
- **Field Options** — select choices and their names, colours, and Airtable IDs.

The JSON download preserves Airtable's table and field definitions and includes the extracted relationships, formulas, and formula dependencies. This makes it suitable for version comparison, further processing, or feeding into other documentation tooling.

Both formats include internal Airtable IDs where useful, making the output suitable for technical work as well as human-readable documentation.

## Requirements and installation

Python 3.11 or later is the supported target.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
# Optional: use this instead of entering the token in the browser
export AIRTABLE_ACCESS_TOKEN="pat_your_token_here"
python app.py
```

Open <http://127.0.0.1:5050>, load the bases available to the token, select one, and download Excel or JSON. Exports are generated in memory, so the browser controls the download location and normal use does not change the repository.

Create an Airtable personal access token with the `schema.bases:read` scope and grant it access only to the bases you want to document. Enter it in the local browser interface, or set `AIRTABLE_ACCESS_TOKEN` as an optional fallback. Browser-entered tokens are held in server memory for 30 minutes, referenced by an opaque identifier during export, and are never rendered back into the page or written to disk. The app does not load `.env` files automatically.

## Security and troubleshooting

Run this only as a local utility. Flask's development server is not a production deployment. Schema exports contain names, IDs, formulas, field options, and other configuration; review them before sharing.

Missing/expired tokens, insufficient permissions, timeouts, rate limits, empty base lists, and unexpected API responses produce controlled messages. For permission failures, confirm both the token scope and its base access.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Tests mock Airtable and require no real token.

## Licence

Licensed under the MIT License. See `LICENSE`.
