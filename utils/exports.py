"""Generate researcher-ready participant exports."""

from __future__ import annotations

from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd


def csv_archive(frames: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, frame in frames.items():
            archive.writestr(f"{name}.csv", frame.to_csv(index=False))
    return output.getvalue()


def excel_workbook(frames: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, frame in frames.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
    return output.getvalue()


def json_export(frames: dict[str, pd.DataFrame]) -> bytes:
    payload = {
        name: json.loads(frame.to_json(orient="records", date_format="iso"))
        for name, frame in frames.items()
    }
    return json.dumps(payload, indent=2).encode("utf-8")

