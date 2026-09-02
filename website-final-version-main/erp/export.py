from __future__ import annotations

import csv
from io import StringIO


def _safe_csv_value(value):
    if not isinstance(value, str):
        return value
    candidate = value.lstrip()
    if candidate.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value


def rows_to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(
        {key: _safe_csv_value(value) for key, value in row.items()}
        for row in rows
    )
    return output.getvalue()
