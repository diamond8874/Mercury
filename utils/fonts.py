import os
import urllib.request
import logging

try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    reportlab_installed = True
except ImportError:
    reportlab_installed = False

def download_lora_fonts():
    font_dir = os.path.join(os.getcwd(), 'fonts')
    os.makedirs(font_dir, exist_ok=True)

    regular_path = os.path.join(font_dir, 'Lora-Regular.ttf')
    bold_path = os.path.join(font_dir, 'Lora-Bold.ttf')

    if not os.path.exists(regular_path):
        logging.info("Downloading Lora-Regular font from Google Fonts...")
        try:
            urllib.request.urlretrieve('https://github.com/cyrealtype/Lora-Cyrillic/raw/main/fonts/ttf/Lora-Regular.ttf', regular_path)
            logging.info("Lora-Regular downloaded successfully.")
        except Exception as e:
            logging.error(f"Failed to download Lora-Regular: {str(e)}")

    if not os.path.exists(bold_path):
        logging.info("Downloading Lora-Bold font from Google Fonts...")
        try:
            urllib.request.urlretrieve('https://github.com/cyrealtype/Lora-Cyrillic/raw/main/fonts/ttf/Lora-Bold.ttf', bold_path)
            logging.info("Lora-Bold downloaded successfully.")
        except Exception as e:
            logging.error(f"Failed to download Lora-Bold: {str(e)}")

    try:
        if reportlab_installed:
            if os.path.exists(regular_path):
                pdfmetrics.registerFont(TTFont('Lora', regular_path))
            if os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont('Lora-Bold', bold_path))
            logging.info("Lora fonts registered successfully in ReportLab.")
    except Exception as e:
        logging.error(f"Failed to register Lora fonts: {str(e)}")
