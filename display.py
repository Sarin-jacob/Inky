import os
import time
from PIL import Image, ImageDraw, ImageFont

# Attempt to load the EPD driver. 
# Wrapping in try/except allows you to test the logic on a PC without the hardware attached.
try:
    from driver.epd7in5b_V2 import EPD
except ImportError:
    print("[-] EPD Driver not found. Running in mock mode.")
    EPD = None

# --- HELPERS ---
def load_fonts():
    """Loads fonts safely with fallbacks."""
    try:
        font_large = ImageFont.truetype("fonts/roboto/Roboto-Black.ttf", 64)
        font_med = ImageFont.truetype("fonts/roboto/Roboto-Regular.ttf", 36)
        font_small = ImageFont.truetype("fonts/roboto/Roboto-Regular.ttf", 24)
        return font_large, font_med, font_small
    except Exception:
        print("[-] Custom fonts not found, using default.")
        default = ImageFont.load_default()
        return default, default, default

def get_sensor_string(dht_sensor):
    """Safely reads the DHT11 sensor."""
    if not dht_sensor:
        return "Sensor Not Configured"
        
    for _ in range(3):
        try:
            temp = dht_sensor.temperature
            hum = dht_sensor.humidity
            if temp is not None and hum is not None:
                return f"Temp: {temp}C  |  Hum: {hum}%"
        except Exception:
            time.sleep(1.0)
    return "Sensor Error"

def get_partial_buffer(img):
    """Bypasses the driver's strict 800x480 size limit for cropped updates."""
    return bytearray(img.convert('1').tobytes('raw'))

def create_blank_layers(width=800, height=480):
    """Returns a blank Black layer and a blank Red layer (255 = White background)."""
    return Image.new('1', (width, height), 255), Image.new('1', (width, height), 255)

# --- HARDWARE DISPLAY COMMANDS ---
def push_full_update(image_black, image_red):
    """Deep flush of the entire screen. Clears ghosting and draws full colors."""
    if not EPD:
        print("[Mock] Full update triggered.")
        return

    epd = EPD()
    epd.init()
    epd.display(epd.getbuffer(image_black), epd.getbuffer(image_red))
    epd.sleep()

def push_partial_update(image_black, x1, y1, x2, y2):
    """
    Blazing fast update of a specific bounding box.
    STRICTLY Black & White. Red layer is ignored to prevent muddy ghosting.
    """
    if not EPD:
        print(f"[Mock] Partial update triggered for box: ({x1}, {y1}, {x2}, {y2})")
        return

    # Crop the exact region from the provided black image
    cropped_region = image_black.crop((x1, y1, x2, y2))
    
    epd = EPD()
    epd.init_part()
    
    # FIX: Pass the absolute x2, y2 coordinates, NOT the calculated width/height!
    epd.display_Partial(get_partial_buffer(cropped_region), x1, y1, x2, y2)
    epd.sleep()