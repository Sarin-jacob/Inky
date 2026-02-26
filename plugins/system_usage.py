# /// script
# requires-python = ">=3.12"
# dependencies = ["psutil", "matplotlib", "requests", "pillow"]
# ///

import os
import time
import io
import collections
import psutil
import requests
from PIL import Image, ImageDraw, ImageFont

# --- CONFIGURATION ---
# Change this to your Pi's IP address or mDNS hostname
API_URL = "http://inky.local/api/push_image"
UPDATE_INTERVAL = 10  # Seconds between updates

# Graph settings
BAR_WIDTH = 8
BAR_GAP = 2
STEP_SIZE = BAR_WIDTH + BAR_GAP
MAX_BARS = 72  # 720 pixels wide / 10 pixels per step = 72 minutes of history
GRAPH_X_START = 40
CPU_Y_START = 260 # Bottom of CPU graph
RAM_Y_START = 440 # Bottom of RAM graph
MAX_HEIGHT = 100

def get_system_temp():
    try:
        temps = psutil.sensors_temperatures()
        for name, entries in temps.items():
            for entry in entries:
                if entry.current > 0:
                    return f"{round(entry.current)}°C"
    except Exception:
        pass
    return "N/A"

def load_font(size):
    try:
        # On Windows 'arial.ttf', Mac 'Arial.ttf', Linux often 'DejaVuSans.ttf' or 'FreeSans.ttf'
        # Fallback list to try
        font_names = ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "FreeSans.ttf"]
        for font in font_names:
            try:
                return ImageFont.truetype(font, size)
            except OSError:
                continue
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()

def push_to_inky(pil_image):
    img_byte_arr = io.BytesIO()
    pil_image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    try:
        print(f"[*] Pushing frame to {API_URL}...")
        # Note: Added timeout to prevent hanging if Pi is offline
        res = requests.post(API_URL, files={'image': ('graph.png', img_byte_arr, 'image/png')}, timeout=5)
        if res.status_code == 200:
            print(f"[+] Server replied: {res.json().get('update_type', 'success')}")
        else:
            print(f"[-] Server error: {res.status_code}")
    except Exception as e:
        print(f"[-] Push failed: {e}")

if __name__ == '__main__':
    print("=== Sweeping Bar Graph Monitor ===")
    
    # Initialize the base canvas state (800x480 is the strict e-ink resolution)
    canvas = Image.new('1', (800, 480), 255) # 255 = White
    draw = ImageDraw.Draw(canvas)
    
    # Reduced font size from 48 to 32 to prevent text cutoff
    font_title = load_font(32) 
    font_labels = load_font(24)
    
    # Draw static gridlines and labels
    draw.text((40, 120), "CPU HISTORY", font=font_labels, fill=0)
    draw.line([(40, 260), (760, 260)], fill=0, width=2) # CPU baseline
    
    draw.text((40, 300), "RAM HISTORY", font=font_labels, fill=0)
    draw.line([(40, 440), (760, 440)], fill=0, width=2) # RAM baseline

    # Push the initial layout to force a full refresh on the e-ink
    push_to_inky(canvas)
    time.sleep(3) 

    tick = 0
    
    try:
        while True:
            cpu_val = psutil.cpu_percent(interval=1)
            ram_val = psutil.virtual_memory().percent
            temp_val = get_system_temp()
            
            # 1. Clear the top text area to draw fresh stats
            # Clears box from (40,20) to (760,100)
            draw.rectangle([(40, 20), (760, 100)], fill=255)
            
            stats_text = f"CPU: {cpu_val}%   |   RAM: {ram_val}%   |   TEMP: {temp_val}"
            
            # Center the text or left align? Left align at 40 is safe now with size 32.
            draw.text((40, 50), stats_text, font=font_title, fill=0)
            
            # 2. Calculate the sweeping X position
            current_idx = tick % MAX_BARS
            x_pos = GRAPH_X_START + (current_idx * STEP_SIZE)
            
            # 3. Create a "Playhead" (Clear the next few bars so it looks like it's overwriting)
            clear_x1 = x_pos
            clear_x2 = x_pos + (STEP_SIZE * 3)
            if clear_x2 > 760: clear_x2 = 760
            
            draw.rectangle([(clear_x1, 140), (clear_x2, 260)], fill=255) # Clear CPU path
            draw.rectangle([(clear_x1, 320), (clear_x2, 440)], fill=255) # Clear RAM path
            
            # 4. Draw the new vertical bars
            # Scale height (0-100%) to pixels (0-100px)
            cpu_h = int((cpu_val / 100) * MAX_HEIGHT)
            ram_h = int((ram_val / 100) * MAX_HEIGHT)
            
            # CPU Bar (Top is Y_START - Height)
            draw.rectangle([(x_pos, CPU_Y_START - cpu_h), (x_pos + BAR_WIDTH, CPU_Y_START)], fill=0)
            # RAM Bar
            draw.rectangle([(x_pos, RAM_Y_START - ram_h), (x_pos + BAR_WIDTH, RAM_Y_START)], fill=0)
            
            # Push to the dashboard
            push_to_inky(canvas)
            
            tick += 1
            time.sleep(UPDATE_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n[*] Stopping monitor.")