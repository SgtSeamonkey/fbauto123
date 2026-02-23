"""
listing_generator.py - Generate listing.txt files for each item.

Creates well-formatted Facebook Marketplace listing detail files
based on Gemini analysis results.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LISTING_TEMPLATE = """\
TITLE: {title}

DESCRIPTION:
{description}

PRICE: ${price:.2f}

CONDITION: {condition}

CATEGORY: {category}

IMAGES: {images}
"""

DEFAULT_PRICE = 10.0


class ListingGenerator:
    """Generates listing.txt files for Facebook Marketplace items."""

    def generate_listing(
        self,
        item_folder: Path,
        analyses: list[dict],
    ) -> Path:
        """
        Generate a listing.txt file for an item in its folder.

        Merges information from all image analyses (in case multiple images
        were analyzed individually) to create a single coherent listing.

        Args:
            item_folder: Path to the item's output folder.
            analyses: List of analysis dicts for this item's images.

        Returns:
            Path to the generated listing.txt file.
        """
        merged = self._merge_analyses(analyses)
        listing_text = LISTING_TEMPLATE.format(
            title=merged["title"],
            description=merged["description"],
            price=merged["price"],
            condition=merged["condition"],
            category=merged["category"],
            images=merged["images"],
        )

        listing_path = item_folder / "listing.txt"
        listing_path.write_text(listing_text, encoding="utf-8")
        logger.info("Generated listing: %s", listing_path)
        return listing_path

    def _merge_analyses(self, analyses: list[dict]) -> dict:
        """
        Merge multiple image analyses into a single listing.

        When multiple images represent the same item, Gemini may have analyzed
        each image separately. This method selects the best values.

        Args:
            analyses: List of analysis result dictionaries.

        Returns:
            Merged dictionary ready for listing generation.
        """
        if not analyses:
            return self._empty_listing()

        # Use the first analysis as the base (it's the primary image)
        base = analyses[0]

        # Pick the most detailed description (longest)
        best_description = max(
            (a.get("description", "") for a in analyses),
            key=len,
            default=base.get("description", "No description available."),
        )

        # Average the prices across analyses
        prices = [a.get("price", DEFAULT_PRICE) for a in analyses if isinstance(a.get("price"), (int, float))]
        avg_price = sum(prices) / len(prices) if prices else DEFAULT_PRICE

        # Pick the most commonly cited condition
        conditions = [a.get("condition", "Good") for a in analyses]
        condition = max(set(conditions), key=conditions.count)

        # Pick the most commonly cited category
        categories = [a.get("category", "Other") for a in analyses]
        category = max(set(categories), key=categories.count)

        # Collect all image names
        image_names = [a.get("image_name", "") for a in analyses if a.get("image_name")]

        # Build a concise title from the item name
        item_name = base.get("item_name", "Item")
        title = self._build_title(item_name, condition)

        return {
            "title": title,
            "description": best_description or "No description available.",
            "price": avg_price,
            "condition": condition,
            "category": category,
            "images": ", ".join(image_names) if image_names else "N/A",
        }

    @staticmethod
    def _build_title(item_name: str, condition: str) -> str:
        """Build a concise marketplace title."""
        item_name = item_name.strip()
        if not item_name or item_name.lower() == "unknown item":
            return "Item for Sale"
        # Append condition only if it's not already in the name
        if condition.lower() not in item_name.lower():
            return f"{item_name} - {condition} Condition"
        return item_name

    @staticmethod
    def _empty_listing() -> dict:
        """Return an empty/default listing structure."""
        return {
            "title": "Item for Sale",
            "description": "No description available.",
            "price": DEFAULT_PRICE,
            "condition": "Good",
            "category": "Other",
            "images": "N/A",
        }

    def get_listing_summary(self, item_folder: Path, analyses: list[dict]) -> dict:
        """
        Return a summary dictionary for use in Excel generation.

        Args:
            item_folder: Path to the item's output folder.
            analyses: List of analysis dicts for this item's images.

        Returns:
            Summary dictionary with all listing fields.
        """
        merged = self._merge_analyses(analyses)
        return {
            "Item Name": analyses[0].get("item_name", "Unknown") if analyses else "Unknown",
            "Title": merged["title"],
            "Description": merged["description"],
            "Price": merged["price"],
            "Condition": merged["condition"],
            "Category": merged["category"],
            "Image Count": len(analyses),
            "Folder Path": str(item_folder),
        }
