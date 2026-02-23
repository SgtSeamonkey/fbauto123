# Facebook Marketplace Listing Automation

Automatically analyze ~400 images of household items and collectibles, organize them into folders, and generate Facebook Marketplace listing details using Google Gemini AI (free tier).

## Features

- 🤖 **AI-powered image analysis** using Google Gemini 1.5 Flash (free tier)
- 📁 **Automatic organization** — groups related images by item into named folders
- 📝 **Listing details** — generates title, description, price, condition, and category
- 📊 **Excel summary** — creates a `summary.xlsx` with all listing details
- ♻️  **Resume capability** — skips already-processed images on re-run
- ⚡ **Rate-limit aware** — respects the free tier (15 RPM) automatically
- 🪵 **Detailed logging** — all operations logged to `marketplace_automation.log`

---

## Quick Start

### 1. Get a Free Google Gemini API Key

1. Visit [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account
3. Click **"Create API key"**
4. Copy the key — you'll need it in step 3

> **Free tier limits:** 15 requests/minute · 1,500 requests/day · 1 million tokens/month
> Processing 400 images should take roughly 30–45 minutes within these limits.

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

## Output Structure

After processing, the `output/` folder will contain:

```
output/
├── vintage_wooden_rocking_chair/
│   ├── photo001.jpg
│   ├── photo002.jpg
│   └── listing.txt
├── nintendo_game_boy_original/
│   ├── photo003.jpg
│   └── listing.txt
├── ...
└── summary.xlsx
```

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

---

## Estimated Processing Time

| Image Count | Estimated Time |
|------------|----------------|
| 50 images | ~5 minutes |
| 100 images | ~10 minutes |
| 200 images | ~20 minutes |
| 400 images | ~35–45 minutes |

Processing is limited by the free API rate limit (15 requests/minute). The app automatically manages this — you don't need to do anything special.

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

If the application is interrupted, simply run `python main.py` again. Images that have already been copied to the output folder will be skipped automatically.

---

## Troubleshooting

### "GEMINI_API_KEY is not set"
- Make sure you copied `config.example.env` to `.env`
- Make sure your API key is on the line `GEMINI_API_KEY=...` (no spaces around `=`)

### "No supported images found"
- Check that your images are in the `images_to_process/` folder (or the folder you specified with `--input`)
- Ensure the file extensions are supported (JPG, PNG, WEBP, etc.)

### "Failed to analyze image"
- The image may be corrupted or in an unsupported sub-format. Check `fbauto123.log` for details.
- Try opening the image in an image viewer to verify it's valid.

### Rate limit errors (429)
- Reduce `MAX_RPM` in your `.env` (e.g., `MAX_RPM=10`)
- Increase `BATCH_DELAY` (e.g., `BATCH_DELAY=10`)

### API quota exceeded
- You've hit the free tier daily limit (1,500 requests/day). Wait until the next day and re-run — the resume feature will pick up where you left off.

### Images not being grouped correctly
- The AI groups images by analyzing visual similarity via item key matching. If items look very similar (e.g., two different chairs), they may be incorrectly grouped. Review the output folders and move images manually as needed.

---

## Project Structure

```
fbauto123/
├── README.md                  # This file
├── requirements.txt           # Python dependencies
├── config.example.env         # Example configuration
├── main.py                    # Entry point
├── src/
│   ├── __init__.py
│   ├── image_analyzer.py      # Gemini API integration
│   ├── image_organizer.py     # Grouping and folder management
│   ├── listing_generator.py   # Listing detail generation
│   └── excel_generator.py     # Excel summary creation
├── images_to_process/         # Place your images here
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
