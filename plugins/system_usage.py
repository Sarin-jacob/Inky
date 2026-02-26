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
import matplotlib.pyplot as plt
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
        # Tries to load standard OS fonts
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()

def push_to_inky(pil_image):
    img_byte_arr = io.BytesIO()
    pil_image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    try:
        print(f"[*] Pushing frame to {API_URL}...")
        res = requests.post(API_URL, files={'image': ('graph.png', img_byte_arr, 'image/png')})
        print(f"[+] Server replied: {res.json()['update_type']}")
    except Exception as e:
        print(f"[-] Push failed: {e}")

if __name__ == '__main__':
    print("=== Sweeping Bar Graph Monitor ===")
    
    # Initialize the base canvas state
    canvas = Image.new('1', (800, 480), 255) # 255 = White
    draw = ImageDraw.Draw(canvas)
    
    font_title = load_font(48)
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
            draw.rectangle([(40, 20), (760, 100)], fill=255)
            stats_text = f"CPU: {cpu_val}%   |   RAM: {ram_val}%   |   TEMP: {temp_val}"
            draw.text((40, 40), stats_text, font=font_title, fill=0)
            
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
            cpu_h = int((cpu_val / 100) * MAX_HEIGHT)
            ram_h = int((ram_val / 100) * MAX_HEIGHT)
            
            # CPU Bar
            draw.rectangle([(x_pos, CPU_Y_START - cpu_h), (x_pos + BAR_WIDTH, CPU_Y_START)], fill=0)
            # RAM Bar
            draw.rectangle([(x_pos, RAM_Y_START - ram_h), (x_pos + BAR_WIDTH, RAM_Y_START)], fill=0)
            
            # Push to the dashboard
            push_to_inky(canvas)
            
            tick += 1
            time.sleep(UPDATE_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n[*] Stopping monitor.")