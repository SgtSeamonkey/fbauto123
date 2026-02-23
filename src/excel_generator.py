"""
excel_generator.py - Create Excel summary spreadsheet.

Generates a master summary.xlsx file in the output folder containing
details for all processed items.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

SUMMARY_COLUMNS = [
    "Item Name",
    "Title",
    "Description",
    "Price",
    "Condition",
    "Category",
    "Image Count",
    "Folder Path",
]


class ExcelGenerator:
    """Generates the master Excel summary spreadsheet."""

    def __init__(self, output_folder: Path) -> None:
        """
        Initialize the ExcelGenerator.

        Args:
            output_folder: Root output directory where summary.xlsx will be saved.
        """
        self.output_folder = output_folder
        self.summary_path = output_folder / "summary.xlsx"

    def generate(self, summaries: list[dict]) -> Path:
        """
        Generate the summary.xlsx file from a list of item summaries.

        Args:
            summaries: List of summary dicts (one per item), each containing
                       the fields defined in SUMMARY_COLUMNS.

        Returns:
            Path to the generated summary.xlsx file.
        """
        if not summaries:
            logger.warning("No items to include in summary spreadsheet.")
            summaries = []

        # Ensure all rows have all required columns
        normalized = []
        for row in summaries:
            normalized.append({col: row.get(col, "") for col in SUMMARY_COLUMNS})

        df = pd.DataFrame(normalized, columns=SUMMARY_COLUMNS)

        # Format price column as currency
        if "Price" in df.columns:
            df["Price"] = pd.to_numeric(df["Price"], errors="coerce").fillna(0.0)

        self._write_excel(df)
        logger.info("Generated summary spreadsheet: %s (%d items)", self.summary_path, len(df))
        return self.summary_path

    def _write_excel(self, df: pd.DataFrame) -> None:
        """Write DataFrame to Excel with basic formatting."""
        with pd.ExcelWriter(self.summary_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Listings")
            worksheet = writer.sheets["Listings"]

            # Auto-fit column widths (approximate)
            for col_idx, column in enumerate(df.columns, start=1):
                max_length = max(
                    len(str(column)),
                    df[column].astype(str).str.len().max() if not df.empty else 0,
                )
                # Cap column width to a reasonable maximum
                col_width = min(max_length + 2, 60)
                col_letter = worksheet.cell(row=1, column=col_idx).column_letter
                worksheet.column_dimensions[col_letter].width = col_width

            # Freeze the header row
            worksheet.freeze_panes = "A2"

    def append_or_update(self, summaries: list[dict]) -> Path:
        """
        Append new items to an existing summary.xlsx, or create it if absent.

        If summary.xlsx already exists, it reads the existing data, merges with
        the new summaries (updating rows with matching Folder Path), and re-saves.

        Args:
            summaries: List of new/updated summary dicts.

        Returns:
            Path to the updated summary.xlsx file.
        """
        if self.summary_path.exists():
            try:
                existing_df = pd.read_excel(self.summary_path)
                existing_records = existing_df.to_dict("records")
                # Index existing records by Folder Path for deduplication
                existing_by_path = {r.get("Folder Path", ""): r for r in existing_records}
                for summary in summaries:
                    existing_by_path[summary.get("Folder Path", "")] = summary
                merged = list(existing_by_path.values())
                return self.generate(merged)
            except Exception as exc:
                logger.warning("Could not read existing summary.xlsx: %s. Overwriting.", exc)

        return self.generate(summaries)
