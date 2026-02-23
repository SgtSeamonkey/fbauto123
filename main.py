"""
main.py - Entry point for the Facebook Marketplace Listing Automation tool.

Usage:
    python main.py [--input INPUT_FOLDER] [--output OUTPUT_FOLDER]

Set your GEMINI_API_KEY in a .env file (copy config.example.env to .env and fill it in).
"""

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import date
from pathlib import Path

from tqdm import tqdm

# Load .env file if present (requires python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on environment variables

from src.excel_generator import ExcelGenerator
from src.image_analyzer import ImageAnalyzer, RateLimitError
from src.image_organizer import ImageOrganizer
from src.item_catalog import ItemCatalog
from src.listing_generator import ListingGenerator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_FILE = "marketplace_automation.log"
PROCESSED_FOLDER = "processed_images"
PROGRESS_FILE = "progress.json"
DEFAULT_MODELS = ["gemini-2.5-flash-lite", "gemini-3-flash", "gemini-2.5-flash"]
DEFAULT_DUPLICATE_MERGE_THRESHOLD = 0.80
DEFAULT_ITEM_CATALOG_FILENAME = "item_catalog.json"

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
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
    raw_models = os.environ.get("GEMINI_MODELS", "").strip()
    if raw_models:
        models = [m.strip() for m in raw_models.split(",") if m.strip()]
    else:
        # Backward-compatible: fall back to single GEMINI_MODEL env var
        single = os.environ.get("GEMINI_MODEL", "").strip()
        models = [single] if single else DEFAULT_MODELS

    return {
        "api_key": os.environ.get("GEMINI_API_KEY", ""),
        "input_folder": os.environ.get("INPUT_FOLDER", "images_to_process"),
        "output_folder": os.environ.get("OUTPUT_FOLDER", "output"),
        "max_rpm": int(os.environ.get("MAX_RPM", "14")),
        "batch_delay": float(os.environ.get("BATCH_DELAY", "5")),
        "batch_size": int(os.environ.get("BATCH_SIZE", "10")),
        "models": models,
        "duplicate_merge_threshold": float(
            os.environ.get("DUPLICATE_MERGE_THRESHOLD", str(DEFAULT_DUPLICATE_MERGE_THRESHOLD))
        ),
        "item_catalog_filename": os.environ.get(
            "ITEM_CATALOG_FILENAME", DEFAULT_ITEM_CATALOG_FILENAME
        ),
    }


# ---------------------------------------------------------------------------
# Progress tracking helpers
# ---------------------------------------------------------------------------

def _load_progress(progress_file: Path) -> dict:
    """Load progress data from progress.json, returning defaults if missing."""
    if progress_file.exists():
        try:
            return json.loads(progress_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "total_images": 0,
        "processed_count": 0,
        "last_run": "",
        "models_used": {},
    }


def _save_progress(progress_file: Path, data: dict) -> None:
    """Persist progress data to progress.json."""
    try:
        progress_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not save progress file: %s", exc)


# ---------------------------------------------------------------------------
# Processed-image helpers
# ---------------------------------------------------------------------------

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".heic"}


def _move_to_processed(image_path: Path, processed_folder: Path) -> bool:
    """
    Move *image_path* into *processed_folder*.

    Handles name collisions by appending a numeric suffix.  Returns True on
    success, False if the move failed.
    """
    dest = processed_folder / image_path.name
    if dest.exists():
        stem = image_path.stem
        suffix = image_path.suffix
        counter = 1
        while dest.exists():
            dest = processed_folder / f"{stem}_{counter}{suffix}"
            counter += 1
    try:
        shutil.move(str(image_path), str(dest))
        logger.info("Moved %s → %s/%s", image_path.name, processed_folder.name, dest.name)
        return True
    except OSError as exc:
        logger.warning("Could not move %s to processed folder: %s", image_path.name, exc)
        return False


def _get_processed_image_names(processed_folder: Path, output_folder: Path) -> set[str]:
    """
    Return filenames of images that have already been processed.

    Checks both *processed_folder* (primary, new) and *output_folder*
    sub-directories (legacy, for backward compatibility with runs made before
    the processed_images/ folder was introduced).
    """
    processed: set[str] = set()

    if processed_folder.exists():
        for f in processed_folder.iterdir():
            if f.is_file() and f.suffix.lower() in SUPPORTED_IMAGE_EXTS:
                processed.add(f.name)

    if output_folder.exists():
        for item_dir in output_folder.iterdir():
            if item_dir.is_dir():
                for f in item_dir.iterdir():
                    if f.is_file() and f.suffix.lower() in SUPPORTED_IMAGE_EXTS:
                        processed.add(f.name)

    return processed


# ---------------------------------------------------------------------------
# Organisation helper (grouping + listing generation)
# ---------------------------------------------------------------------------

def _organize_and_list(
    analyses: list[dict],
    organizer: ImageOrganizer,
    listing_gen: ListingGenerator,
    catalog: ItemCatalog,
) -> list[dict]:
    """
    Group analyses by item, create output folders, write listings.

    For each group, checks the item catalog for a cross-run duplicate.  When a
    match is found at or above the configured threshold the new images are merged
    into the existing folder instead of creating a fresh one.

    Returns a list of summary dicts (one per item group).
    """
    summaries: list[dict] = []

    groups = organizer.group_analyses_by_item(analyses)

    duplicate_warnings = organizer.detect_similar_groups(groups)
    for warning in duplicate_warnings:
        logger.warning(warning)
        print(f"  ⚠  {warning}")

    today_str = date.today().isoformat()

    for item_key, item_analyses in groups.items():
        item_name = item_analyses[0].get("item_name", item_key)
        canonical_text = ItemCatalog.build_canonical_text(item_key, item_analyses)
        image_names = [a.get("image_name", "") for a in item_analyses if a.get("image_name")]

        # --- Cross-run duplicate check ---
        match = catalog.find_match(canonical_text, item_key)
        if match is not None:
            existing_entry, similarity = match
            existing_key = existing_entry["item_key"]
            existing_folder = organizer.get_or_create_item_folder(existing_key)

            if existing_folder is not None:
                # Merge: copy images into the existing folder
                for analysis in item_analyses:
                    src = Path(analysis["image_path"])
                    if src.exists():
                        organizer.copy_image_to_folder(src, existing_folder)

                # Write a listing_update file (never overwrite listing.txt)
                update_filename = f"listing_update_{today_str}.txt"
                update_path = existing_folder / update_filename
                # Handle multiple updates on the same day
                if update_path.exists():
                    counter = 2
                    while update_path.exists():
                        update_path = existing_folder / f"listing_update_{today_str}_{counter}.txt"
                        counter += 1

                merged = listing_gen._merge_analyses(item_analyses)
                update_text = (
                    f"MERGED INTO: {existing_key}\n"
                    f"SIMILARITY SCORE: {similarity:.4f}\n"
                    f"MERGE DATE: {today_str}\n"
                    f"\n"
                    f"--- New Analysis Summary ---\n"
                    f"TITLE: {merged['title']}\n"
                    f"\n"
                    f"DESCRIPTION:\n{merged['description']}\n"
                    f"\n"
                    f"PRICE: ${merged['price']:.2f}\n"
                    f"CONDITION: {merged['condition']}\n"
                    f"CATEGORY: {merged['category']}\n"
                    f"IMAGES: {merged['images']}\n"
                )
                update_path.write_text(update_text, encoding="utf-8")

                # Update catalog entry with new images
                catalog.update_entry_images(existing_key, image_names)

                logger.info(
                    "Merged '%s' into existing '%s' (similarity: %.2f)",
                    item_key, existing_key, similarity,
                )
                print(f"  🔁 Merged '{item_key}' into existing '{existing_key}' (similarity: {similarity:.2f})")

                summary = listing_gen.get_listing_summary(existing_folder, item_analyses)
                summaries.append(summary)
                continue

        # --- No match: create a new item folder as normal ---
        existing_folder = organizer.get_or_create_item_folder(item_key)
        if existing_folder and organizer.is_already_processed(existing_folder):
            logger.info("Skipping already-processed item: %s", item_key)
            print(f"  ↷  Skipping (already processed): {item_key}")
            continue

        item_folder = organizer.create_item_folder(item_key, item_name)

        for analysis in item_analyses:
            src = Path(analysis["image_path"])
            if src.exists():
                organizer.copy_image_to_folder(src, item_folder)

        listing_gen.generate_listing(item_folder, item_analyses)
        summary = listing_gen.get_listing_summary(item_folder, item_analyses)
        summaries.append(summary)

        # Add new entry to catalog
        title = listing_gen._merge_analyses(item_analyses)["title"]
        catalog.add_entry(item_key, title, canonical_text, image_names)

        print(f"  ✓  {item_name} → {item_folder.name}/")

    return summaries


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

    input_folder = Path(args.input or config["input_folder"])
    output_folder = Path(args.output or config["output_folder"])
    processed_folder = Path(PROCESSED_FOLDER)
    api_key = config["api_key"]
    models = config["models"]

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

    # --- Create output/processed folders ---
    output_folder.mkdir(parents=True, exist_ok=True)
    processed_folder.mkdir(exist_ok=True)

    # --- Resume capability: skip already-processed images ---
    processed_names = _get_processed_image_names(processed_folder, output_folder)
    remaining_images = [img for img in all_images if img.name not in processed_names]

    print(f"\n📂 Input folder    : {input_folder}/")
    print(f"📦 Output folder   : {output_folder}/")
    print(f"📁 Processed folder: {processed_folder}/")
    print(f"🖼  Images found    : {len(all_images)}")
    print(f"🤖 Models          : {', '.join(models)}")
    print(f"⏱  Rate limit      : {config['max_rpm']} requests/minute")
    print()

    if processed_names:
        skipped = len(all_images) - len(remaining_images)
        print(f"↷  Resuming: {skipped} image(s) already processed, {len(remaining_images)} remaining.\n")

    if not remaining_images:
        print("✅ All images have already been processed!")
        print(
            f"\n✅ Done! Check the '{output_folder}/' folder for organized items.\n"
            f"   Log file: {LOG_FILE}\n"
        )
        return

    # --- Initialise components ---
    model_index = 0
    current_model = models[model_index]
    analyzer = ImageAnalyzer(api_key=api_key, max_rpm=config["max_rpm"], model_name=current_model)
    organizer = ImageOrganizer(output_folder=output_folder)
    listing_gen = ListingGenerator()
    excel_gen = ExcelGenerator(output_folder=output_folder)
    catalog = ItemCatalog(
        catalog_path=output_folder / config["item_catalog_filename"],
        threshold=config["duplicate_merge_threshold"],
    )

    logger.info("Using model: %s", current_model)
    print(f"🚀 Starting with model: {current_model}")
    print(f"   Processing {len(remaining_images)} image(s)...\n")

    # --- Analyse images one by one, switching models on rate-limit errors ---
    all_analyses: list[dict] = []
    successfully_analyzed: list[Path] = []
    models_used: dict[str, int] = {}
    all_exhausted = False

    with tqdm(total=len(remaining_images), desc="Analyzing images", unit="img") as pbar:
        for image_path in remaining_images:
            if all_exhausted:
                break

            # Inner retry loop: retry the same image after a model switch
            while True:
                try:
                    result = analyzer.analyze_image(image_path)
                    if result:
                        all_analyses.append(result)
                        successfully_analyzed.append(image_path)
                        models_used[current_model] = models_used.get(current_model, 0) + 1
                    else:
                        logger.warning(
                            "Skipping image (analysis failed): %s", image_path.name
                        )
                    pbar.update(1)
                    break  # Move on to next image

                except RateLimitError as exc:
                    print(
                        f"\n⚠️  Model '{exc.model_name}' has hit its rate limit."
                    )
                    logger.warning("Rate limit hit for model: %s", exc.model_name)
                    model_index += 1
                    if model_index < len(models):
                        current_model = models[model_index]
                        print(f"✓  Switching to next model: '{current_model}'\n")
                        logger.info("Switching to model: %s", current_model)
                        analyzer.switch_model(current_model)
                        # Retry the same image with the new model
                    else:
                        print("\n⚠️  All available models have reached their daily limits.")
                        logger.warning("All models exhausted.")
                        all_exhausted = True
                        pbar.update(1)
                        break

    # --- Organize and generate listings ---
    all_summaries: list[dict] = []
    if all_analyses:
        print("\n📁 Organizing items and generating listings...")
        all_summaries = _organize_and_list(all_analyses, organizer, listing_gen, catalog)
        catalog.save()

    # --- Move successfully analyzed images to processed_images/ ---
    moved_count = 0
    for image_path in successfully_analyzed:
        if _move_to_processed(image_path, processed_folder):
            moved_count += 1

    # --- Generate / update Excel summary ---
    if all_summaries:
        excel_path = excel_gen.append_or_update(all_summaries)
        print(f"\n📊 Summary spreadsheet saved: {excel_path}")
    elif not all_analyses:
        print("\n⚠  No items were successfully processed.")

    # --- Save progress.json ---
    progress_file = Path(PROGRESS_FILE)
    progress = _load_progress(progress_file)
    # Update cumulative totals
    prev_processed = progress.get("processed_count", 0)
    progress["processed_count"] = prev_processed + len(successfully_analyzed)
    remaining_after = len(ImageAnalyzer.get_supported_images(input_folder))
    progress["total_images"] = progress["processed_count"] + remaining_after
    progress["last_run"] = str(date.today())
    for model_name, count in models_used.items():
        progress.setdefault("models_used", {})[model_name] = (
            progress["models_used"].get(model_name, 0) + count
        )
    _save_progress(progress_file, progress)

    # --- Final summary ---
    print(f"\n✓  Processing complete!")
    print(f"   - Total images processed this run : {len(successfully_analyzed)}")
    print(f"   - Images moved to {processed_folder}/  : {moved_count}")
    print(f"   - Images remaining in {input_folder}/  : {remaining_after}")
    if all_exhausted:
        print(f"   - All available models have reached their daily limits")
        print(f"   - Run this script again tomorrow to continue processing")

    print(
        f"\n✅ Done! Check the '{output_folder}/' folder for organized items.\n"
        f"   Log file: {LOG_FILE}\n"
    )


if __name__ == "__main__":
    main()

