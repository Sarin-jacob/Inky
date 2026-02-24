import os
import time
import json
import threading
from datetime import datetime
import board
import adafruit_dht
import RPi.GPIO as GPIO
from flask import Flask, render_template, request, redirect, url_for
from PIL import Image, ImageDraw, ImageFont

# Hardware Imports (Assuming driver folder is in the same directory)
from driver.epd7in5b import EPD

# Ensure time is handled correctly for your region
os.environ['TZ'] = 'Asia/Kolkata'
time.tzset()

# --- CONFIGURATION & STATE ---
UPLOAD_DIR = 'uploads'
STATE_FILE = 'state.json'
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Default State
state = {
    "active_page": 1,
    "calendar_source": "todoist",
    "photo_path": ""
}

# Thread-safe flag to tell the main loop to update the screen
needs_refresh = True 

app = Flask(__name__)

# --- HARDWARE SETUP ---
DHT_PIN = board.D5
try:
    dht_sensor = adafruit_dht.DHT11(DHT_PIN) 
except Exception:
    pass # Handle gracefully if missing

BTN_PAGE_1 = 6
BTN_PAGE_2 = 13
BTN_PAGE_3 = 19
BTN_EXTRA  = 26

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    buttons = [BTN_PAGE_1, BTN_PAGE_2, BTN_PAGE_3, BTN_EXTRA]
    for btn in buttons:
        GPIO.setup(btn, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(btn, GPIO.FALLING, callback=button_callback, bouncetime=500)

def button_callback(channel):
    global needs_refresh
    if channel == BTN_PAGE_1: state['active_page'] = 1
    elif channel == BTN_PAGE_2: state['active_page'] = 2
    elif channel == BTN_PAGE_3: state['active_page'] = 3
    elif channel == BTN_EXTRA: pass # Free for future use
    
    save_state()
    needs_refresh = True

# --- STATE MANAGEMENT ---
def load_state():
    global state
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            state.update(json.load(f))

def save_state():
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# --- IMAGE PROCESSING (Convert to RBW for Driver) ---
def process_upload(filepath):
    """ Converts image to the specific Grayscale format the driver expects """
    img = Image.open(filepath).resize((640, 384)).convert("RGB")
    
    # 3-color palette mapping
    palettedata = [255, 255, 255,  0, 0, 0,  255, 0, 0] # White, Black, Red
    palettedata.extend([0] * (768 - len(palettedata)))
    palimage = Image.new('P', (1, 1))
    palimage.putpalette(palettedata)
    
    img_converted = img.quantize(palette=palimage)
    
    # Map back to L values expected by driver: Black(<64), Red(<192), White(>192)
    img_gray = Image.new('L', (640, 384))
    p_new = img_gray.load()
    p_old = img_converted.load()
    
    for y in range(384):
        for x in range(640):
            if p_old[x, y] == 0: p_new[x,y] = 255   # White
            elif p_old[x, y] == 1: p_new[x,y] = 0   # Black
            elif p_old[x, y] == 2: p_new[x,y] = 128 # Red
            
    final_path = os.path.join(UPLOAD_DIR, 'display.bmp')
    img_gray.save(final_path)
    return final_path

# --- WEB SERVER ROUTES ---
@app.route('/', methods=['GET', 'POST'])
def index():
    global needs_refresh
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'set_page':
            state['active_page'] = int(request.form.get('page'))
        elif action == 'set_source':
            state['calendar_source'] = request.form.get('source')
        elif action == 'upload':
            file = request.files.get('image')
            if file:
                temp_path = os.path.join(UPLOAD_DIR, 'temp.jpg')
                file.save(temp_path)
                state['photo_path'] = process_upload(temp_path)
                state['active_page'] = 3
                
        save_state()
        needs_refresh = True
        return redirect(url_for('index'))
        
    return render_template('index.html', state=state)

# --- HARDWARE DISPLAY LOOP ---
def draw_display():
    epd = EPD()
    epd.init()
    
    image = Image.new('L', (640, 384), 255) # 255 is white
    draw = ImageDraw.Draw(image)
    
    # Load a default font
    font_large = ImageFont.truetype("fonts/roboto/Roboto-Black.ttf", 48)
    font_med = ImageFont.truetype("fonts/roboto/Roboto-Regular.ttf", 24)
    
    # Sensor Reading
    try:
        temp = dht_sensor.temperature
        hum = dht_sensor.humidity
        sensor_str = f"Temp: {temp}C | Hum: {hum}%" if temp else "Sensor Data Unavailable"
    except Exception:
        sensor_str = "Sensor Error"

    page = state['active_page']
    
    if page == 1:
        # PAGE 1: Clock & Calendar
        now = datetime.now()
        draw.text((20, 50), now.strftime("%I:%M %p"), font=font_large, fill=0) # Black
        draw.text((20, 120), now.strftime("%A, %B %d"), font=font_med, fill=128) # Red
        draw.text((20, 340), sensor_str, font=font_med, fill=0)
        
    elif page == 2:
        # PAGE 2: Todoist / Google Cal (Integrate API calls here)
        source = state['calendar_source'].upper()
        draw.text((20, 20), f"{source} TASKS", font=font_large, fill=128) # Red
        draw.text((20, 100), "1. Example Task 1", font=font_med, fill=0)
        draw.text((20, 140), "2. Example Task 2", font=font_med, fill=0)
        draw.text((20, 340), sensor_str, font=font_med, fill=0)
        
    elif page == 3:
        # PAGE 3: Photo Viewer
        if state['photo_path'] and os.path.exists(state['photo_path']):
            photo = Image.open(state['photo_path'])
            image.paste(photo, (0,0))
        else:
            draw.text((100, 150), "NO PHOTO UPLOADED", font=font_large, fill=128)
            
    # Send to driver
    epd.display_frame(epd.get_frame_buffer(image))
    epd.sleep()

def hardware_loop():
    global needs_refresh
    last_refresh_time = time.time()
    
    while True:
        # Auto-refresh Page 1 every 5 minutes, or instantly if a button/web change happened
        time_elapsed = time.time() - last_refresh_time
        if needs_refresh or (state['active_page'] == 1 and time_elapsed > 300):
            print("Refreshing display...")
            draw_display()
            needs_refresh = False
            last_refresh_time = time.time()
            
        time.sleep(1) # Small sleep to prevent CPU hogging

# --- ENTRY POINT ---
if __name__ == '__main__':
    load_state()
    setup_gpio()
    
    # Start Web Server in background thread
    web_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False))
    web_thread.daemon = True
    web_thread.start()
    
    try:
        print("Starting Hardware Loop...")
        hardware_loop()
    except KeyboardInterrupt:
        print("Shutting down...")
        GPIO.cleanup()