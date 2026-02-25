"""
item_catalog.py - Persistent item catalog for cross-run duplicate detection and merging.

Maintains a JSON catalog of known items to enable automatic merging of duplicate
items discovered across multiple runs of the application.
"""

import json
import logging
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ItemCatalog:
    """Manages a persistent catalog of known items for cross-run duplicate detection."""

    def __init__(self, catalog_path: Path, threshold: float = 0.80) -> None:
        """
        Initialize the ItemCatalog.

        Args:
            catalog_path: Path to the JSON catalog file.
            threshold: Minimum similarity score to consider items as duplicates.
        """
        self.catalog_path = catalog_path
        self.threshold = threshold
        self._entries: list[dict] = []
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load existing catalog entries from the JSON file."""
        if self.catalog_path.exists():
            try:
                data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._entries = data
                    logger.info(
                        "Loaded %d item(s) from catalog: %s",
                        len(self._entries),
                        self.catalog_path,
                    )
                else:
                    logger.warning(
                        "Catalog file has unexpected format; starting fresh: %s",
                        self.catalog_path,
                    )
                    self._entries = []
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load catalog (%s); starting fresh.", exc)
                self._entries = []
        else:
            self._entries = []

    def save(self) -> None:
        """Persist catalog entries to the JSON file."""
        try:
            self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
            self.catalog_path.write_text(
                json.dumps(self._entries, indent=2), encoding="utf-8"
            )
            logger.debug("Saved %d catalog entries to %s", len(self._entries), self.catalog_path)
        except OSError as exc:
            logger.warning("Could not save catalog: %s", exc)

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def find_match(
        self, canonical_text: str, item_key: str
    ) -> Optional[tuple[dict, float]]:
        """
        Find the best matching catalog entry for a new item.

        Similarity is calculated by combining SequenceMatcher scores on
        both the canonical_text and item_key fields, giving canonical_text
        more weight.

        Args:
            canonical_text: The canonical text representation of the new item.
            item_key: The snake_case key for the new item.

        Returns:
            Tuple of (matching catalog entry, similarity score) if a match
            is found at or above the threshold, otherwise None.
        """
        best_entry = None
        best_score = 0.0

        for entry in self._entries:
            score = self._compute_similarity(
                canonical_text,
                item_key,
                entry.get("canonical_text", ""),
                entry.get("item_key", ""),
            )
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry is not None and best_score >= self.threshold:
            return best_entry, best_score
        return None

    @staticmethod
    def _compute_similarity(
        text_a: str, key_a: str, text_b: str, key_b: str
    ) -> float:
        """
        Compute a combined similarity score between two items.

        Weights: 60% canonical_text similarity + 20% item_key character similarity
        + 20% item_key token-overlap (Jaccard).  The Jaccard component makes
        cross-run matching resilient to different word orderings in the key
        (e.g. ``blue_ceramic_mug`` vs ``ceramic_blue_mug``).
        """
        text_score = SequenceMatcher(None, text_a.lower(), text_b.lower()).ratio()
        key_score = SequenceMatcher(None, key_a.lower(), key_b.lower()).ratio()
        tokens_a = set(key_a.lower().split("_"))
        tokens_b = set(key_b.lower().split("_"))
        if tokens_a and tokens_b:
            intersection = tokens_a & tokens_b
            union = tokens_a | tokens_b
            token_score = len(intersection) / len(union)
        else:
            token_score = 0.0
        return 0.60 * text_score + 0.20 * key_score + 0.20 * token_score

    # ------------------------------------------------------------------
    # Catalog management
    # ------------------------------------------------------------------

    @staticmethod
    def build_canonical_text(item_key: str, analyses: list[dict]) -> str:
        """
        Build a canonical text representation from analysis results.

        Combines the item key and key attributes for similarity comparison.

        Args:
            item_key: Snake_case item key.
            analyses: List of analysis dicts for this item.

        Returns:
            A single string suitable for similarity comparison.
        """
        parts = [item_key.replace("_", " ")]
        if analyses:
            base = analyses[0]
            if base.get("item_name"):
                parts.append(base["item_name"])
            if base.get("category"):
                parts.append(base["category"])
            if base.get("condition"):
                parts.append(base["condition"])
            # Include the longest description for more signal
            best_desc = max(
                (a.get("description", "") for a in analyses), key=len, default=""
            )
            if best_desc:
                parts.append(best_desc)
        return " ".join(parts)

    def add_entry(
        self,
        item_key: str,
        title: str,
        canonical_text: str,
        image_names: Optional[list[str]] = None,
    ) -> dict:
        """
        Add a new entry to the catalog.

        If an entry with the same item_key already exists it is updated in-place.

        Args:
            item_key: Snake_case key identifying the item.
            title: Human-readable listing title.
            canonical_text: Canonical text for similarity matching.
            image_names: Optional list of representative image filenames.

        Returns:
            The newly added or updated catalog entry.
        """
        now = datetime.utcnow().isoformat()
        for entry in self._entries:
            if entry.get("item_key") == item_key:
                entry["title"] = title
                entry["canonical_text"] = canonical_text
                entry["updated_at"] = now
                if image_names is not None:
                    existing = entry.get("representative_image_names", [])
                    entry["representative_image_names"] = list(
                        dict.fromkeys(existing + image_names)
                    )
                return entry

        entry = {
            "item_key": item_key,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "canonical_text": canonical_text,
            "representative_image_names": image_names or [],
        }
        self._entries.append(entry)
        return entry

    def update_entry_images(self, item_key: str, new_image_names: list[str]) -> None:
        """
        Append new image names to an existing catalog entry's image list.

        Args:
            item_key: The item_key of the entry to update.
            new_image_names: New image filenames to add.
        """
        now = datetime.utcnow().isoformat()
        for entry in self._entries:
            if entry.get("item_key") == item_key:
                existing = entry.get("representative_image_names", [])
                entry["representative_image_names"] = list(
                    dict.fromkeys(existing + new_image_names)
                )
                entry["updated_at"] = now
                return
