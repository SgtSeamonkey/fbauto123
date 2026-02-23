"""
main.py - Entry point for the Facebook Marketplace Listing Automation tool.

Usage:
    python main.py [--input INPUT_FOLDER] [--output OUTPUT_FOLDER]

Set your GEMINI_API_KEY in a .env file (copy config.example.env to .env and fill it in).
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from tqdm import tqdm

# Load .env file if present (requires python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on environment variables

from src.excel_generator import ExcelGenerator
from src.image_analyzer import ImageAnalyzer
from src.image_organizer import ImageOrganizer
from src.listing_generator import ListingGenerator

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_FILE = "marketplace_automation.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_config() -> dict:
    """Read configuration from environment variables."""
    return {
        "api_key": os.environ.get("GEMINI_API_KEY", ""),
        "input_folder": os.environ.get("INPUT_FOLDER", "images_to_process"),
        "output_folder": os.environ.get("OUTPUT_FOLDER", "output"),
        "max_rpm": int(os.environ.get("MAX_RPM", "14")),
        "batch_size": int(os.environ.get("BATCH_SIZE", "10")),
        "batch_delay": float(os.environ.get("BATCH_DELAY", "5")),
        "model_name": os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"),
    }


# ---------------------------------------------------------------------------
# Core processing logic
# ---------------------------------------------------------------------------

def _process_batch(
    batch: list[Path],
    analyzer: ImageAnalyzer,
    organizer: ImageOrganizer,
    listing_gen: ListingGenerator,
    batch_delay: float,
) -> list[dict]:
    """
    Process a batch of images: analyze, group, copy to folders, write listings.

    Args:
        batch: List of image paths to process.
        analyzer: ImageAnalyzer instance.
        organizer: ImageOrganizer instance.
        listing_gen: ListingGenerator instance.
        batch_delay: Seconds to wait after processing the batch.

    Returns:
        List of summary dicts (one per item group found in this batch).
    """
    summaries: list[dict] = []

    # --- Step 1: Analyze each image individually ---
    analyses: list[dict] = []
    for image_path in batch:
        logger.info("Analyzing image: %s", image_path.name)
        result = analyzer.analyze_image(image_path)
        if result:
            analyses.append(result)
        else:
            logger.warning("Skipping image (analysis failed): %s", image_path.name)

    if not analyses:
        return summaries

    # --- Step 2: Group analyses by item key ---
    groups = organizer.group_analyses_by_item(analyses)

    # --- Step 3: Detect potential duplicates across groups ---
    duplicate_warnings = organizer.detect_similar_groups(groups)
    for warning in duplicate_warnings:
        logger.warning(warning)
        print(f"  ⚠  {warning}")

    # --- Step 4: For each group, create folder, copy images, write listing ---
    for item_key, item_analyses in groups.items():
        item_name = item_analyses[0].get("item_name", item_key)

        # Check if this item was already processed in a previous run
        existing_folder = organizer.get_or_create_item_folder(item_key)
        if existing_folder and organizer.is_already_processed(existing_folder):
            logger.info("Skipping already-processed item: %s", item_key)
            print(f"  ↷  Skipping (already processed): {item_key}")
            continue

        # Create the output folder
        item_folder = organizer.create_item_folder(item_key, item_name)

        # Copy images into the item folder
        for analysis in item_analyses:
            src = Path(analysis["image_path"])
            if src.exists():
                organizer.copy_image_to_folder(src, item_folder)

        # Generate listing.txt
        listing_gen.generate_listing(item_folder, item_analyses)

        # Collect summary for Excel
        summary = listing_gen.get_listing_summary(item_folder, item_analyses)
        summaries.append(summary)

        print(f"  ✓  {item_name} → {item_folder.name}/")

    # --- Step 5: Pause between batches to respect rate limits ---
    if batch_delay > 0:
        time.sleep(batch_delay)

    return summaries


def _get_already_processed_image_names(output_folder: Path) -> set[str]:
    """
    Return the set of image filenames that have already been copied to output.

    Used for resume capability: images that exist anywhere in the output tree
    are considered already processed.
    """
    processed: set[str] = set()
    for item_dir in output_folder.iterdir():
        if item_dir.is_dir():
            for f in item_dir.iterdir():
                if f.is_file() and f.suffix.lower() in {
                    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".heic"
                }:
                    processed.add(f.name)
    return processed


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(
        description="Facebook Marketplace Listing Automation using Google Gemini AI"
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Input folder containing images (default: images_to_process/)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output folder for organized items (default: output/)",
    )
    args = parser.parse_args()

    config = _get_config()

    # Command-line args override environment variables
    input_folder = Path(args.input or config["input_folder"])
    output_folder = Path(args.output or config["output_folder"])
    api_key = config["api_key"]

    print("=" * 60)
    print("  Facebook Marketplace Listing Automation")
    print("=" * 60)

    # --- Validate API key ---
    if not api_key:
        print(
            "\n❌ ERROR: GEMINI_API_KEY is not set.\n"
            "  1. Copy config.example.env to .env\n"
            "  2. Add your API key (get one free at https://aistudio.google.com/app/apikey)\n"
            "  3. Run again.\n"
        )
        sys.exit(1)

    # --- Validate input folder ---
    if not input_folder.exists():
        print(f"\n❌ ERROR: Input folder not found: {input_folder}")
        print("  Create the folder and add your images, then run again.\n")
        sys.exit(1)

    # --- Discover images ---
    all_images = ImageAnalyzer.get_supported_images(input_folder)

    if not all_images:
        print(f"\n⚠  No supported images found in {input_folder}/")
        print("  Supported formats: JPG, JPEG, PNG, GIF, BMP, WEBP, TIFF, HEIC\n")
        sys.exit(0)

    print(f"\n📂 Input folder : {input_folder}/")
    print(f"📦 Output folder: {output_folder}/")
    print(f"🖼  Images found : {len(all_images)}")
    print(f"🤖 Using model  : {config['model_name']} (free tier)")
    print(f"⏱  Rate limit   : {config['max_rpm']} requests/minute")
    print()

    # --- Resume capability: skip already-processed images ---
    output_folder.mkdir(parents=True, exist_ok=True)
    processed_names = _get_already_processed_image_names(output_folder)
    remaining_images = [img for img in all_images if img.name not in processed_names]

    if processed_names:
        skipped = len(all_images) - len(remaining_images)
        print(f"↷  Resuming: {skipped} image(s) already processed, {len(remaining_images)} remaining.\n")

    if not remaining_images:
        print("✅ All images have already been processed!")
    else:
        # --- Initialise components ---
        analyzer = ImageAnalyzer(api_key=api_key, max_rpm=config["max_rpm"], model_name=config["model_name"])
        organizer = ImageOrganizer(output_folder=output_folder)
        listing_gen = ListingGenerator()
        excel_gen = ExcelGenerator(output_folder=output_folder)

        # --- Process in batches ---
        batch_size = config["batch_size"]
        batches = [
            remaining_images[i: i + batch_size]
            for i in range(0, len(remaining_images), batch_size)
        ]

        all_summaries: list[dict] = []
        estimated_minutes = len(remaining_images) / config["max_rpm"]
        print(
            f"🚀 Processing {len(remaining_images)} images in {len(batches)} batch(es).\n"
            f"   Estimated time: ~{estimated_minutes:.0f} minute(s) (within free tier limits).\n"
        )

        with tqdm(total=len(remaining_images), desc="Processing images", unit="img") as pbar:
            for batch_num, batch in enumerate(batches, start=1):
                logger.info(
                    "Processing batch %d/%d (%d images)", batch_num, len(batches), len(batch)
                )
                batch_summaries = _process_batch(
                    batch=batch,
                    analyzer=analyzer,
                    organizer=organizer,
                    listing_gen=listing_gen,
                    batch_delay=config["batch_delay"],
                )
                all_summaries.extend(batch_summaries)
                pbar.update(len(batch))

        # --- Generate / update Excel summary ---
        if all_summaries:
            excel_path = excel_gen.append_or_update(all_summaries)
            print(f"\n📊 Summary spreadsheet saved: {excel_path}")
        else:
            print("\n⚠  No items were successfully processed.")

    print(
        f"\n✅ Done! Check the '{output_folder}/' folder for organized items.\n"
        f"   Log file: marketplace_automation.log\n"
    )


if __name__ == "__main__":
    main()
