# Facebook Marketplace Listing Automation

Automatically analyze ~400 images of household items and collectibles, organize them into folders, and generate Facebook Marketplace listing details using Google Gemini AI (free tier).

## Features

- 🤖 **AI-powered image analysis** using Google Gemini (multiple models with automatic failover)
- 📁 **Automatic organization** — groups related images by item into named folders
- 📝 **Listing details** — generates title, description, price, condition, and category
- 📊 **Excel summary** — creates a `summary.xlsx` with all listing details
- ♻️  **Resume capability** — skips already-processed images on re-run; processed images are moved to `processed_images/`
- 🔄 **Multi-model failover** — automatically switches to the next model when a daily rate limit is hit
- ⚡ **Rate-limit aware** — respects the free tier (15 RPM) automatically
- 🪵 **Detailed logging** — all operations logged to `marketplace_automation.log`
- 📈 **Progress tracking** — saves cumulative run statistics to `progress.json`

---

## Quick Start

### 1. Get a Free Google Gemini API Key

1. Visit [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account
3. Click **"Create API key"**
4. Copy the key — you'll need it in step 3

> **Free tier limits (per model):** ~10–15 requests/minute · 20 requests/day (varies by model)
> With three models in the failover chain you can process up to ~40 images per day.

---

### 2. Set Up the Project

```bash
# Clone the repo (or download it)
git clone https://github.com/SgtSeamonkey/fbauto123.git
cd fbauto123

# Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate       # macOS / Linux
venv\Scripts\activate          # Windows

# Install dependencies
pip install -r requirements.txt
```

---

### 3. Configure Your API Key

```bash
# Copy the example config file
cp config.example.env .env

# Open .env and replace 'your_api_key_here' with your actual key
```

Your `.env` file should look like:

```
GEMINI_API_KEY=AIzaSy...your_key_here...
```

---

### 4. Add Your Images

Place all your images in the `images_to_process/` folder:

```
fbauto123/
└── images_to_process/
    ├── photo001.jpg
    ├── photo002.jpg
    ├── photo003.jpg
    └── ...
```

**Supported formats:** JPG, JPEG, PNG, GIF, BMP, WEBP, TIFF, HEIC

---

### 5. Run the Application

```bash
python main.py
```

Optional arguments:

```bash
python main.py --input /path/to/my/photos --output /path/to/results
```

---

## Folder Structure

```
fbauto123/
├── images_to_process/     # Place your unprocessed images here
├── processed_images/      # Processed images are moved here automatically
└── output/                # Organized item folders and listings appear here
    ├── vintage_wooden_rocking_chair/
    │   ├── photo001.jpg
    │   └── listing.txt
    ├── nintendo_game_boy_original/
    │   ├── photo003.jpg
    │   └── listing.txt
    └── summary.xlsx
```

After each run:
- Successfully analyzed images are **moved** from `images_to_process/` to `processed_images/`
- Item folders and listings are written to `output/`
- A cumulative `progress.json` is updated

---

## Multi-Model Failover

The app cycles through multiple Gemini models when daily rate limits are reached:

| Model | RPM | RPD |
|-------|-----|-----|
| `gemini-2.5-flash-lite` | 10 | 20 |
| `gemini-3-flash` | 5 | 20 |
| `gemini-2.5-flash` | 5 | 20 |

**Behaviour:**
1. Processing starts with `gemini-2.5-flash-lite`
2. When a 429 (RESOURCE_EXHAUSTED) error is received, the app switches to the next model automatically
3. When all models are exhausted the app displays a summary and exits gracefully
4. Run `python main.py` again the next day — it resumes from where it left off

**Console output during a switch:**
```
⚠️  Model 'gemini-2.5-flash-lite' has hit its rate limit (20 RPD).
✓  Switching to next model: 'gemini-3-flash'
```

**End-of-run summary:**
```
✓  Processing complete!
   - Total images processed this run : 40
   - Images moved to processed_images/  : 40
   - Images remaining in images_to_process/  : 383
   - All available models have reached their daily limits
   - Run this script again tomorrow to continue processing
```

---

## Example Multi-Day Workflow

**Day 1:**
```bash
python main.py
# Processes ~40 images (20 per model × 2 models)
# Moves 40 images to processed_images/
# Shows: "383 images remaining. Run again tomorrow!"
```

**Day 2:**
```bash
python main.py
# Processes next ~40 images (skips the 40 already in processed_images/)
# Shows: "343 images remaining. Run again tomorrow!"
```

Continue until all images are processed.

---

## Output Structure

### listing.txt Format

```
TITLE: Vintage Wooden Rocking Chair - Good Condition

DESCRIPTION:
A beautiful vintage wooden rocking chair with carved armrests and a woven seat...

PRICE: $85.00

CONDITION: Good

CATEGORY: Furniture

IMAGES: photo001.jpg, photo002.jpg
```

### summary.xlsx Columns

| Column | Description |
|--------|-------------|
| Item Name | Descriptive item name from AI |
| Title | Marketplace listing title |
| Description | Detailed description |
| Price | Recommended price (USD) |
| Condition | New / Like New / Good / Fair / Poor |
| Category | Facebook Marketplace category |
| Image Count | Number of images for this item |
| Folder Path | Path to the item's output folder |

### progress.json

Tracks cumulative processing statistics across multiple runs:

```json
{
  "total_images": 423,
  "processed_count": 40,
  "last_run": "2026-02-23",
  "models_used": {
    "gemini-2.5-flash-lite": 20,
    "gemini-3-flash": 20
  }
}
```

---

## Configuration Options

All settings can be configured via environment variables in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | *(required)* | Your Google Gemini API key |
| `INPUT_FOLDER` | `images_to_process` | Folder containing input images |
| `OUTPUT_FOLDER` | `output` | Folder for organized output |
| `MAX_RPM` | `14` | Max API requests per minute (free tier: 15) |
| `BATCH_SIZE` | `10` | Images per processing batch |
| `BATCH_DELAY` | `5` | Seconds to pause between batches |
| `GEMINI_MODELS` | `gemini-2.5-flash-lite,gemini-3-flash,gemini-2.5-flash` | Comma-separated list of models to try in order |
| `GEMINI_MODEL` | *(see note)* | Single model override (used only when `GEMINI_MODELS` is not set) |

---

## Estimated Processing Time

With the default three-model chain (~40 images/day):

| Total Images | Estimated Days |
|-------------|----------------|
| 40 images | 1 day |
| 200 images | ~5 days |
| 400 images | ~10 days |

---

## Supported Facebook Marketplace Categories

- Electronics
- Home & Garden
- Clothing & Accessories
- Collectibles
- Sports & Outdoors
- Toys & Games
- Furniture
- Appliances
- Tools
- Books & Media
- Antiques
- Other

---

## Resume / Re-running

Simply run `python main.py` again at any time. The app:
- Checks `processed_images/` for images already handled
- Checks `output/` sub-folders for backward compatibility
- Only processes images not yet seen in either location

---

## Troubleshooting

### "GEMINI_API_KEY is not set"
- Make sure you copied `config.example.env` to `.env`
- Make sure your API key is on the line `GEMINI_API_KEY=...` (no spaces around `=`)

### "No supported images found"
- Check that your images are in the `images_to_process/` folder (or the folder you specified with `--input`)
- Ensure the file extensions are supported (JPG, PNG, WEBP, etc.)

### "Failed to analyze image"
- The image may be corrupted or in an unsupported sub-format. Check `marketplace_automation.log` for details.
- Try opening the image in an image viewer to verify it's valid.

### Rate limit errors (429)
- The app automatically switches to the next model in the list.
- When all models are exhausted it exits gracefully — run again tomorrow.
- To adjust limits: set `MAX_RPM` in your `.env` (e.g., `MAX_RPM=10`)

### API quota exceeded
- You've hit the free tier daily limit for all configured models.
- Wait until the next day and re-run — the resume feature picks up where you left off.

### Images not being grouped correctly
- The AI groups images by analyzing visual similarity via item key matching. If items look very similar (e.g., two different chairs), they may be incorrectly grouped. Review the output folders and move images manually as needed.

---

## Project Structure

```
fbauto123/
├── README.md                  # This file
├── requirements.txt           # Python dependencies
├── config.example.env         # Example configuration
├── progress.json              # Auto-generated run statistics (gitignored)
├── main.py                    # Entry point
├── src/
│   ├── __init__.py
│   ├── image_analyzer.py      # Gemini API integration + RateLimitError
│   ├── image_organizer.py     # Grouping and folder management
│   ├── listing_generator.py   # Listing detail generation
│   └── excel_generator.py     # Excel summary creation
├── images_to_process/         # Place your images here
├── processed_images/          # Processed images moved here automatically
└── output/                    # Organized items appear here
```

---

## Requirements

- Python 3.10 or newer
- A free Google Gemini API key
- Internet connection (for API calls)

---

## License

MIT
