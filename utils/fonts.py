import os
import urllib.request
import logging

try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    reportlab_installed = True
except ImportError:
    reportlab_installed = False

FONT_SOURCES = {
    'Lora-Regular.ttf': 'https://github.com/cyrealtype/Lora-Cyrillic/raw/main/fonts/ttf/Lora-Regular.ttf',
    'Lora-Bold.ttf': 'https://github.com/cyrealtype/Lora-Cyrillic/raw/main/fonts/ttf/Lora-Bold.ttf',
}

# Fonts are cosmetic: never let a slow or offline network stall app startup.
DOWNLOAD_TIMEOUT = 10


def download_lora_fonts():
    """Fetch and register the Lora report fonts. Silently degrades to Helvetica."""
    font_dir = os.path.join(os.getcwd(), 'fonts')
    os.makedirs(font_dir, exist_ok=True)

    regular_path = os.path.join(font_dir, 'Lora-Regular.ttf')
    bold_path = os.path.join(font_dir, 'Lora-Bold.ttf')

    for filename, url in FONT_SOURCES.items():
        target = os.path.join(font_dir, filename)
        if os.path.exists(target):
            continue
        logging.info(f"Downloading {filename} from Google Fonts...")
        try:
            with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response:
                data = response.read()
            with open(target, 'wb') as handle:
                handle.write(data)
            logging.info(f"{filename} downloaded successfully.")
        except Exception as e:
            logging.warning(f"Failed to download {filename} ({e}); the PDF will fall back to Helvetica.")

    try:
        if reportlab_installed:
            if os.path.exists(regular_path):
                pdfmetrics.registerFont(TTFont('Lora', regular_path))
            if os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont('Lora-Bold', bold_path))
            logging.info("Lora fonts registered successfully in ReportLab.")
    except Exception as e:
        logging.error(f"Failed to register Lora fonts: {str(e)}")
