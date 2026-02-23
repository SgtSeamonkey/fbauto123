"""
image_organizer.py - Image grouping and folder management.

Groups related images by item and creates organized folder structure
in the output directory.
"""

import logging
import re
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum Jaccard similarity between item keys to trigger a duplicate warning
DUPLICATE_SIMILARITY_THRESHOLD = 0.6


class ImageOrganizer:
    """Organizes images into item folders based on analysis results."""

    def __init__(self, output_folder: Path) -> None:
        """
        Initialize the ImageOrganizer.

        Args:
            output_folder: Root output directory where item folders will be created.
        """
        self.output_folder = output_folder
        self.output_folder.mkdir(parents=True, exist_ok=True)

    def create_item_folder(self, item_key: str, item_name: str) -> Path:
        """
        Create a uniquely named folder for an item.

        Args:
            item_key: Snake_case key identifying the item type.
            item_name: Human-readable item name.

        Returns:
            Path to the created (or existing) item folder.
        """
        # Build a safe folder name from the item key
        folder_name = self._make_folder_name(item_key)
        folder_path = self.output_folder / folder_name

        # Handle collisions by appending a counter
        if folder_path.exists():
            counter = 2
            while True:
                candidate = self.output_folder / f"{folder_name}_{counter}"
                if not candidate.exists():
                    folder_path = candidate
                    break
                counter += 1

        folder_path.mkdir(parents=True, exist_ok=True)
        logger.debug("Created item folder: %s", folder_path)
        return folder_path

    def get_or_create_item_folder(self, item_key: str) -> Optional[Path]:
        """
        Return an existing item folder that matches item_key, or None.

        Args:
            item_key: Snake_case key identifying the item type.

        Returns:
            Existing folder path or None if not found.
        """
        folder_name = self._make_folder_name(item_key)
        folder_path = self.output_folder / folder_name
        if folder_path.exists():
            return folder_path
        return None

    def copy_image_to_folder(self, source: Path, dest_folder: Path) -> Path:
        """
        Copy an image into the destination folder.

        Args:
            source: Source image path.
            dest_folder: Destination folder path.

        Returns:
            Path to the copied image.
        """
        dest = dest_folder / source.name
        # Avoid overwriting by appending suffix if file already exists
        if dest.exists():
            stem = source.stem
            suffix = source.suffix
            counter = 2
            while dest.exists():
                dest = dest_folder / f"{stem}_{counter}{suffix}"
                counter += 1
        shutil.copy2(source, dest)
        logger.debug("Copied %s -> %s", source, dest)
        return dest

    def get_existing_item_folders(self) -> list[Path]:
        """Return all item folders that already exist in the output directory."""
        return sorted(
            [
                p
                for p in self.output_folder.iterdir()
                if p.is_dir() and not p.name.startswith(".")
            ]
        )

    def is_already_processed(self, item_folder: Path) -> bool:
        """Check whether an item folder has already been fully processed."""
        listing_file = item_folder / "listing.txt"
        return listing_file.exists()

    @staticmethod
    def _make_folder_name(item_key: str) -> str:
        """Convert an item key into a clean folder name."""
        name = item_key.strip().lower()
        name = re.sub(r"[^\w\s-]", "", name)
        name = re.sub(r"[\s-]+", "_", name)
        name = name.strip("_")
        return name or "unknown_item"

    def group_analyses_by_item(
        self, analyses: list[dict]
    ) -> dict[str, list[dict]]:
        """
        Group image analysis results by item key.

        Images with the same item_key (from Gemini analysis) are grouped together.
        This is a heuristic grouping; compare_images_for_grouping in ImageAnalyzer
        provides more accurate grouping via visual comparison.

        Args:
            analyses: List of analysis result dictionaries.

        Returns:
            Dictionary mapping item_key -> list of analysis dicts.
        """
        groups: dict[str, list[dict]] = {}
        for analysis in analyses:
            key = analysis.get("item_key", "unknown_item")
            groups.setdefault(key, []).append(analysis)
        return groups

    def detect_similar_groups(self, groups: dict[str, list[dict]]) -> list[str]:
        """
        Detect potentially duplicate item groups and return warning messages.

        Args:
            groups: Dictionary of item_key -> list of analysis dicts.

        Returns:
            List of warning strings for potentially similar items.
        """
        warnings = []
        keys = list(groups.keys())
        for i, key_a in enumerate(keys):
            for key_b in keys[i + 1:]:
                similarity = self._key_similarity(key_a, key_b)
                if similarity >= DUPLICATE_SIMILARITY_THRESHOLD:
                    warnings.append(
                        f"WARNING: Possible duplicate items detected: "
                        f"'{key_a}' and '{key_b}' (similarity: {similarity:.0%}). "
                        "Please review these folders."
                    )
        return warnings

    @staticmethod
    def _key_similarity(key_a: str, key_b: str) -> float:
        """Calculate simple token-overlap similarity between two item keys."""
        tokens_a = set(key_a.split("_"))
        tokens_b = set(key_b.split("_"))
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)
