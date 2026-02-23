"""
image_analyzer.py - Google Gemini AI image analysis for Facebook Marketplace items.

Uses the Google Gemini API to analyze product images and extract structured
listing data (item name, description, price, condition, category).
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from PIL import Image
import google.genai as genai

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when the API returns a 429 / RESOURCE_EXHAUSTED error."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(f"Rate limit reached for model: {model_name}")

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".heic"
}

ANALYSIS_PROMPT = """Analyze this image of a household item or collectible for a Facebook Marketplace listing.
Respond ONLY with a valid JSON object (no markdown, no extra text) with these exact fields:
{
  "item_name": "A descriptive name for the item (e.g., 'Vintage Wooden Rocking Chair')",
  "item_key": "snake_case_key (e.g., 'vintage_wooden_rocking_chair')",
  "description": "A detailed description suitable for a Facebook Marketplace listing (2-4 sentences)",
  "price": <recommended price as a number (no $ sign)>,
  "condition": "One of: New, Like New, Good, Fair, Poor",
  "category": "One of: Electronics, Home & Garden, Clothing & Accessories, Collectibles, Sports & Outdoors, Toys & Games, Furniture, Appliances, Tools, Books & Media, Antiques, Other"
}"""

FACEBOOK_CATEGORIES = {
    "Electronics",
    "Home & Garden",
    "Clothing & Accessories",
    "Collectibles",
    "Sports & Outdoors",
    "Toys & Games",
    "Furniture",
    "Appliances",
    "Tools",
    "Books & Media",
    "Antiques",
    "Other",
}

CONDITIONS = {"New", "Like New", "Good", "Fair", "Poor"}


class ImageAnalyzer:
    """Analyzes images using Google Gemini AI to extract marketplace listing data."""

    def __init__(
        self,
        api_key: str,
        max_rpm: int = 14,
        model_name: str = "models/gemini-1.5-flash-latest",
    ) -> None:
        """
        Initialize the ImageAnalyzer.

        Args:
            api_key: Google Gemini API key.
            max_rpm: Maximum requests per minute (to respect rate limits).
            model_name: Gemini model to use for image analysis.
        """
        self.model_name = model_name
        self.max_rpm = max_rpm
        self._min_interval = 60.0 / max_rpm  # seconds between requests
        self._last_request_time: float = 0.0
        self._client = genai.Client(api_key=api_key)
        logger.info(
            "ImageAnalyzer initialized (model=%s, max_rpm=%d)", model_name, max_rpm
        )

    def switch_model(self, new_model_name: str) -> None:
        """Switch to a different Gemini model at runtime.

        Args:
            new_model_name: The name of the new model to use.
        """
        self.model_name = new_model_name
        logger.info("Switched to model: %s", new_model_name)

    def analyze_image(self, image_path: Path) -> Optional[dict]:
        """
        Analyze a single image and return structured marketplace listing data.

        Args:
            image_path: Path to the image file.

        Returns:
            Dictionary with item details, or None if analysis fails.
        """
        try:
            self._rate_limit()
            image = Image.open(image_path)
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=[ANALYSIS_PROMPT, image],
            )
            raw_text = response.text.strip()
            result = self._parse_response(raw_text)
            if result is None:
                logger.warning("Failed to parse Gemini response for %s", image_path.name)
                return None

            # Normalize and validate fields
            result["item_name"] = result.get("item_name", "Unknown Item").strip()
            result["item_key"] = self._normalize_key(
                result.get("item_key") or result["item_name"]
            )
            result["description"] = result.get("description", "").strip()
            result["price"] = self._parse_price(result.get("price"))
            result["condition"] = self._normalize_condition(result.get("condition", "Good"))
            result["category"] = self._normalize_category(result.get("category", "Other"))
            result["image_name"] = image_path.name
            result["image_path"] = str(image_path)
            logger.info(
                "Analyzed %s -> %s ($%.2f)",
                image_path.name,
                result["item_name"],
                result["price"],
            )
            return result
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                raise RateLimitError(self.model_name)
            logger.error("Error analyzing image %s: %s", image_path.name, exc)
            return None

    @staticmethod
    def get_supported_images(folder: Path) -> list[Path]:
        """
        Return a sorted list of supported image files in the given folder.

        Args:
            folder: Directory to search for images.

        Returns:
            Sorted list of image paths.
        """
        images = []
        for path in folder.iterdir():
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                images.append(path)
        return sorted(images)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Sleep if necessary to stay within the max requests-per-minute limit."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    @staticmethod
    def _parse_response(raw_text: str) -> Optional[dict]:
        """Parse the Gemini JSON response, stripping markdown fences if present."""
        text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return None

    @staticmethod
    def _normalize_key(raw_key: str) -> str:
        """Convert a string to a snake_case item key."""
        key = raw_key.strip().lower()
        key = re.sub(r"[^\w\s-]", "", key)
        key = re.sub(r"[\s-]+", "_", key)
        key = key.strip("_")
        return key or "unknown_item"

    @staticmethod
    def _parse_price(raw_price) -> float:
        """Parse and validate a price value, returning a sensible default."""
        if isinstance(raw_price, (int, float)) and raw_price >= 0:
            return float(raw_price)
        if isinstance(raw_price, str):
            cleaned = re.sub(r"[^\d.]", "", raw_price)
            try:
                value = float(cleaned)
                if value >= 0:
                    return value
            except ValueError:
                pass
        return 10.0

    @staticmethod
    def _normalize_condition(condition: str) -> str:
        """Normalize the condition to one of the accepted values."""
        if condition in CONDITIONS:
            return condition
        for c in CONDITIONS:
            if c.lower() == condition.lower():
                return c
        return "Good"

    @staticmethod
    def _normalize_category(category: str) -> str:
        """Normalize the category to one of the accepted Facebook Marketplace values."""
        if category in FACEBOOK_CATEGORIES:
            return category
        for c in FACEBOOK_CATEGORIES:
            if c.lower() == category.lower():
                return c
        return "Other"