"""
image_analyzer.py - Google Gemini API integration for image analysis.

Analyzes images using the Gemini Vision API to identify items,
assess condition, and extract relevant details for marketplace listings.
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from PIL import Image

logger = logging.getLogger(__name__)

# Supported image extensions
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".heic"}

# Facebook Marketplace categories
FB_CATEGORIES = [
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
]

# Facebook Marketplace conditions
FB_CONDITIONS = ["New", "Like New", "Good", "Fair", "Poor"]


class ImageAnalyzer:
    """Analyzes images using Google Gemini Vision API."""

    def __init__(self, api_key: str, max_rpm: int = 14, model_name: str = "gemini-1.5-flash") -> None:
        """
        Initialize the ImageAnalyzer.

        Args:
            api_key: Google Gemini API key.
            max_rpm: Maximum API requests per minute (default 14 to stay under 15 RPM free tier).
            model_name: Gemini model to use (default: gemini-1.5-flash).
        """
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.max_rpm = max_rpm
        self._request_times: list[float] = []

    def _rate_limit(self) -> None:
        """Enforce rate limiting to stay within free tier limits."""
        now = time.monotonic()
        # Remove timestamps older than 60 seconds
        self._request_times = [t for t in self._request_times if now - t < 60.0]

        if len(self._request_times) >= self.max_rpm:
            # Wait until the oldest request falls outside the 60-second window
            wait_time = 60.0 - (now - self._request_times[0]) + 0.5
            if wait_time > 0:
                logger.info("Rate limit reached. Waiting %.1f seconds...", wait_time)
                time.sleep(wait_time)

        self._request_times.append(time.monotonic())

    def _load_image(self, image_path: Path) -> Optional[Image.Image]:
        """Load and validate an image file."""
        try:
            img = Image.open(image_path)
            img.verify()
            # Re-open after verify (verify closes the file)
            img = Image.open(image_path)
            # Convert to RGB if necessary (e.g., RGBA, P mode)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            return img
        except Exception as exc:
            logger.warning("Failed to load image %s: %s", image_path, exc)
            return None

    def analyze_image(self, image_path: Path) -> Optional[dict]:
        """
        Analyze a single image and return structured item information.

        Args:
            image_path: Path to the image file.

        Returns:
            Dictionary with item analysis or None on failure.
        """
        img = self._load_image(image_path)
        if img is None:
            return None

        prompt = (
            "Analyze this image of a household item or collectible for a Facebook Marketplace listing. "
            "Respond with ONLY a structured answer using EXACTLY this format (no extra text):\n\n"
            "ITEM_NAME: [short descriptive name, e.g. 'Vintage Wooden Rocking Chair']\n"
            "ITEM_KEY: [snake_case identifier for grouping same items, e.g. 'vintage_wooden_rocking_chair']\n"
            "DESCRIPTION: [2-4 sentence detailed description mentioning brand, material, color, dimensions if visible, notable features]\n"
            "CONDITION: [one of: New, Like New, Good, Fair, Poor]\n"
            "CONDITION_NOTES: [brief notes on visible wear, damage, or why you chose this condition]\n"
            "PRICE: [numeric value only, e.g. 45]\n"
            "PRICE_REASONING: [one sentence explaining the price based on item type, brand, condition, and typical resale value]\n"
            f"CATEGORY: [one of: {', '.join(FB_CATEGORIES)}]\n\n"
            "Be specific and realistic. For pricing, consider the used resale market (not retail)."
        )

        try:
            self._rate_limit()
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[prompt, img],
            )
            return self._parse_analysis_response(response.text, image_path)
        except Exception as exc:
            logger.error("Failed to analyze image %s: %s", image_path, exc)
            return None

    def _parse_analysis_response(self, text: str, image_path: Path) -> dict:
        """Parse the structured response from Gemini into a dictionary."""
        result: dict = {
            "image_path": str(image_path),
            "image_name": image_path.name,
            "item_name": "Unknown Item",
            "item_key": "unknown_item",
            "description": "",
            "condition": "Good",
            "condition_notes": "",
            "price": 10.0,
            "price_reasoning": "",
            "category": "Other",
            "raw_response": text,
        }

        field_map = {
            "ITEM_NAME": "item_name",
            "ITEM_KEY": "item_key",
            "DESCRIPTION": "description",
            "CONDITION": "condition",
            "CONDITION_NOTES": "condition_notes",
            "PRICE": "price",
            "PRICE_REASONING": "price_reasoning",
            "CATEGORY": "category",
        }

        for line in text.strip().splitlines():
            for prefix, key in field_map.items():
                if line.startswith(f"{prefix}:"):
                    value = line[len(prefix) + 1:].strip()
                    if key == "price":
                        try:
                            result[key] = float(value.replace("$", "").replace(",", ""))
                        except ValueError:
                            result[key] = 10.0
                    elif key == "condition" and value not in FB_CONDITIONS:
                        # Fuzzy match condition - check longer values first to avoid
                        # "New" matching before "Like New"
                        matched = False
                        for cond in sorted(FB_CONDITIONS, key=len, reverse=True):
                            if cond.lower() in value.lower():
                                result[key] = cond
                                matched = True
                                break
                        if not matched:
                            result[key] = "Good"  # safe default
                    elif key == "category" and value not in FB_CATEGORIES:
                        result[key] = "Other"
                    else:
                        result[key] = value
                    break

        # Sanitize item_key for use as folder name
        result["item_key"] = self._sanitize_key(result["item_key"])
        return result

    @staticmethod
    def _sanitize_key(key: str) -> str:
        """Sanitize item key to be a valid folder name."""
        key = key.lower().strip()
        key = re.sub(r"[^\w\s-]", "", key)
        key = re.sub(r"[\s-]+", "_", key)
        key = key.strip("_")
        return key or "unknown_item"

    def compare_images_for_grouping(self, image_paths: list[Path]) -> list[list[Path]]:
        """
        Analyze multiple images to determine which ones show the same item.

        Uses Gemini to compare images and group them by item identity.

        Args:
            image_paths: List of image paths to compare.

        Returns:
            List of groups, where each group is a list of paths showing the same item.
        """
        if not image_paths:
            return []
        if len(image_paths) == 1:
            return [image_paths]

        images = []
        valid_paths = []
        for p in image_paths:
            img = self._load_image(p)
            if img is not None:
                images.append(img)
                valid_paths.append(p)

        if not images:
            return []

        filenames = [p.name for p in valid_paths]
        prompt = (
            f"I have {len(images)} images. Determine which images show the SAME physical item "
            "(i.e., multiple photos of the same object from different angles or distances). "
            "Group them accordingly.\n\n"
            f"Image filenames in order: {filenames}\n\n"
            "Respond with ONLY this format (no extra text):\n"
            "GROUP_1: [comma-separated filenames of images showing the same item]\n"
            "GROUP_2: [comma-separated filenames]\n"
            "...and so on. Each image must appear in exactly one group. "
            "If an image is unique, it gets its own group."
        )

        try:
            self._rate_limit()
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[prompt] + images,
            )
            return self._parse_grouping_response(response.text, valid_paths)
        except Exception as exc:
            logger.error("Failed to compare images for grouping: %s", exc)
            # Fall back: each image is its own group
            return [[p] for p in valid_paths]

    def _parse_grouping_response(self, text: str, valid_paths: list[Path]) -> list[list[Path]]:
        """Parse the grouping response into lists of path groups."""
        path_by_name = {p.name: p for p in valid_paths}
        groups: list[list[Path]] = []
        assigned: set[str] = set()

        for line in text.strip().splitlines():
            if not line.startswith("GROUP_"):
                continue
            parts = line.split(":", 1)
            if len(parts) < 2:
                continue
            filenames_str = parts[1].strip()
            group_paths = []
            for fname in filenames_str.split(","):
                fname = fname.strip()
                if fname in path_by_name and fname not in assigned:
                    group_paths.append(path_by_name[fname])
                    assigned.add(fname)
            if group_paths:
                groups.append(group_paths)

        # Add any unassigned paths as individual groups
        for p in valid_paths:
            if p.name not in assigned:
                groups.append([p])

        return groups

    @staticmethod
    def get_supported_images(folder: Path) -> list[Path]:
        """Return all supported image files in a folder (non-recursive)."""
        images = []
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
                images.append(f)
        return images
