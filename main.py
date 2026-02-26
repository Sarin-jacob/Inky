import os
import time
import threading
from datetime import datetime
import RPi.GPIO as GPIO
import board
import adafruit_dht
from PIL import Image, ImageDraw
import textwrap

# Import our new modular tools
from utils import load_state, save_state, register_mdns
from display import push_full_update, push_partial_update, get_sensor_data, create_blank_layers, load_fonts
from app import create_app
from api_handler import get_world_clocks, get_weather, get_todoist_tasks, get_picture_of_the_day, get_calendar_events
from quote_manager import get_next_quote

# --- CONFIGURATION & STATE ---
os.environ['TZ'] = 'Asia/Kolkata'
time.tzset()

restart_flag=0 #make 1 when buttons are fixed

UPLOAD_DIR = 'uploads'
POTD_DIR= f"{UPLOAD_DIR}/potd"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(POTD_DIR, exist_ok=True)


# Shared state and thread-safe flags
state = load_state()
flag_full_refresh = True
flag_partial_refresh = False
partial_bbox = None

# Callback functions for Flask to trigger updates on the main hardware thread
def trigger_full_refresh():
    global flag_full_refresh
    flag_full_refresh = True

def trigger_partial_refresh(bbox):
    global flag_partial_refresh, partial_bbox
    partial_bbox = bbox
    flag_partial_refresh = True

# --- HARDWARE SETUP ---
try:
    dht_sensor = adafruit_dht.DHT11(board.D5) 
except Exception:
    dht_sensor = None

BTN_PAGE_1 = 6
BTN_PAGE_2 = 13
BTN_PAGE_3 = 19
BTN_EXTRA  = 26

def delayed_reboot():
    global state
    state['is_rebooting'] = True
    trigger_full_refresh()
    save_state(state)
    print("[!] System rebooting in 5 seconds...")
    time.sleep(5)
    os.system('sudo reboot')

def cycle_mode(page):
    """Cycles through modes (1-3) for a given page."""
    global state
    if state['active_page'] != page:
        state['active_page'] = page
        state['active_mode'] = 1
    else:
        state['active_mode'] = (state.get('active_mode', 1) % 3) + 1
    print(f"[*] Page {page} Mode changed to {state['active_mode']}")

def button_callback(channel):
    # 20ms debounce
    time.sleep(0.02)
    if GPIO.input(channel) != GPIO.LOW:
        return 
        
    print(f"[HW] Button {channel} pressed.", flush=True)
    start_time = time.time()
    is_long_press = False
    is_reboot_combo = False

    # Track how long the button is held
    while GPIO.input(channel) == GPIO.LOW:
        time.sleep(0.1)
        elapsed = time.time() - start_time
        
        # Check for 5-Second Dual Hold (Btn 1 + Btn 3)
        if GPIO.input(BTN_PAGE_1) == GPIO.LOW and GPIO.input(BTN_PAGE_3) == GPIO.LOW:
            if elapsed >= 5.0:
                is_reboot_combo = True
                break
                
        # Check for 3-Second Single Hold
        elif elapsed >= 3.0:
            is_long_press = True
            break

    # Execute Action
    if is_reboot_combo and restart_flag:
        print("[!] Reboot combo detected!")
        threading.Thread(target=delayed_reboot).start()
        return
        
    elif is_long_press:
        if channel == BTN_PAGE_1: cycle_mode(1)
        elif channel == BTN_PAGE_2: cycle_mode(2)
        elif channel == BTN_PAGE_3: cycle_mode(3)
        elif channel == BTN_EXTRA: 
            print("[*] Force Sync APIs Triggered!") 
            
    else:
        # Short Press Actions
        if channel == BTN_PAGE_1: state['active_page'] = 1
        elif channel == BTN_PAGE_2: state['active_page'] = 2
        elif channel == BTN_PAGE_3: state['active_page'] = 3
        elif channel == BTN_EXTRA: 
            print("[*] Manual screen refresh triggered.")
            
    save_state(state)
    trigger_full_refresh()

def setup_gpio():
    print("[*] Setting up GPIO buttons...", flush=True)
    try:
        GPIO.setmode(GPIO.BCM)
        for btn in [BTN_PAGE_1, BTN_PAGE_2, BTN_PAGE_3, BTN_EXTRA]:
            GPIO.setup(btn, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.remove_event_detect(btn) 
            GPIO.add_event_detect(btn, GPIO.FALLING, callback=button_callback, bouncetime=200)
    except Exception as e:
        print(f"[-] FAILED GPIO Setup: {e}")

# --- DISPLAY RENDERER ---
def render_current_state(time_str, sensor_data):
    """Builds the full screen image based on the current state and APIs."""
    img_black, img_red = create_blank_layers()
    draw_black, draw_red = ImageDraw.Draw(img_black), ImageDraw.Draw(img_red)
    font_large, font_med, font_small = load_fonts()
    
    page = state.get('active_page', 1)
    mode = state.get('active_mode', 1)

    if state.get('is_rebooting'):
        draw_red.text((250, 200), "REBOOTING...", font=font_large, fill=0)
        draw_black.text((260, 280), "Please wait 60 seconds.", font=font_med, fill=0)

    # ==========================================
    # PAGE 1: THE DAILY HUB
    # ==========================================
    elif page == 1:
        if mode ==1: # Unified Time & Weather Dashboard
            # --- LEFT SIDE: TIME & DATE ---
            # Main local time
            draw_black.text((40, 60), time_str, font=font_large, fill=0)
            draw_red.text((40, 150), datetime.now().strftime("%A, %B %d"), font=font_med, fill=0)
            
            # Secondary Clocks
            tz_configs = [
                {"name": state.get('tz1_name', 'CEST'), "tz": state.get('tz1_zone', 'Europe/Paris')},
                {"name": state.get('tz2_name', 'NY'), "tz": state.get('tz2_zone', 'America/New_York')},
                {"name": state.get('tz3_name', 'TYO'), "tz": state.get('tz3_zone', 'Asia/Tokyo')}
            ]
            
            clocks = get_world_clocks(tz_configs)
            draw_black.text((40, 220), "WORLD CLOCKS", font=font_small, fill=0)
            y_offset=260
            for clock in clocks['additional']:
                draw_black.text((80, y_offset), f"{clock['name'].upper()}: {clock['time']}", font=font_med, fill=0)
                y_offset+=60

            # --- RIGHT SIDE: WEATHER & SENSORS ---
            # Draw a subtle dividing line
            draw_black.line([(420, 40), (420, 440)], fill=0, width=2)
            
            weather_key = state.get('openweather_api_key', '')
            weather = get_weather(weather_key)
            
            if "error" in weather:
                draw_red.text((450, 60), weather["error"], font=font_med, fill=0)
            else:
                # Weather Icon
                paths = weather.get("icon_paths")
                if paths and os.path.exists(paths["black"]) and os.path.exists(paths["red"]):
                    weather_icon_black = Image.open(paths["black"])
                    weather_icon_red = Image.open(paths["red"])
                    
                    img_black.paste(weather_icon_black, (450, 60))
                    img_red.paste(weather_icon_red, (450, 60))
                
                # Big Temperature
                draw_black.text((580, 60), f"{weather['temp']}°C", font=font_large, fill=0)
                
                # City & Conditions
                draw_black.text((450, 160), weather['city'].upper(), font=font_small, fill=0)
                draw_red.text((450, 200), weather['description'], font=font_med, fill=0)
                
                # Extra Weather Stats
                stats_str = f"H: {weather['temp_max']}°  L: {weather['temp_min']}°\nFeels like: {weather['feels_like']}°\nWind: {weather['wind_speed']} m/s"
                draw_black.text((450, 260), stats_str, font=font_small, fill=0)

            # --- BOTTOM: DHT11 SENSOR ---
            if sensor_data is None:
                draw_black.text((450, 410), "Sensor Not Configured", font=font_med, fill=0)
            elif "error" in sensor_data:
                draw_red.text((450, 410), "Sensor Read Error", font=font_med, fill=0)
            else:
                draw_black.text((450, 375), "INDOOR SENSOR:", font=font_small, fill=0)
                # Load your custom icon images
                try:
                    icon_thermo = Image.open("icons/thermo.png").convert("1").resize((32, 32))
                    icon_drop = Image.open("icons/drop.png").convert("1").resize((32, 32))
                    
                    # Draw Thermometer Icon and Temp text
                    img_red.paste(icon_thermo, (450, 410)) # Pasting to img_red makes the icon red!
                    draw_black.text((485, 405), f"{sensor_data['temp']}°C", font=font_med, fill=0)
                    
                    # Draw Droplet Icon and Humidity text
                    img_black.paste(icon_drop, (600, 410)) 
                    draw_black.text((635, 405), f"{sensor_data['hum']}%", font=font_med, fill=0)
                except Exception:
                    # Fallback if you haven't downloaded the thermo.png/drop.png files yet
                    draw_black.text((450, 405), f"T: {sensor_data['temp']}°C   H: {sensor_data['hum']}%", font=font_med, fill=0)
            
        elif mode == 2: # Daily Quotes
            draw_red.text((40, 40), "QUOTE OF THE MOMENT", font=font_small, fill=0)
            
            # Pass our state and our draw object (so the engine can measure pixel text width)
            quote_data = get_next_quote(state, draw_black)
            
            if "error" in quote_data:
                draw_red.text((40, 200), "QUOTE ENGINE ERROR", font=font_large, fill=0)
                draw_black.text((40, 280), quote_data["error"], font=font_med, fill=0)
            else:
                # Unpack the layout engine results
                lines = quote_data["lines"]
                author = quote_data["author"]
                font_q = quote_data["font_quote"]
                font_a = quote_data["font_author"]
                lh = quote_data["line_height"]
                
                # Draw the quote text centered vertically in our bounding box
                y_offset = 120 
                for line in lines:
                    draw_black.text((40, y_offset), line, font=font_q, fill=0)
                    y_offset += lh
                    
                # Draw the author slightly below the quote in Red
                y_offset += 20
                draw_red.text((80, y_offset), f"— {author}", font=font_a, fill=0)
            
            # Keep a small clock at the very bottom so you don't lose track of time!
            draw_black.text((40, 440), f"Local: {time_str}", font=font_small, fill=0)
            
        elif mode == 3: # Custom API Push (B&W Only)
            api_img_path = os.path.join(UPLOAD_DIR, 'api_current.bmp')
            if os.path.exists(api_img_path):
                api_img = Image.open(api_img_path).convert('1').resize((800, 480))
                img_black.paste(api_img, (0, 0))
            else:
                draw_black.text((150, 200), "WAITING FOR API PUSH", font=font_large, fill=0)
                draw_black.text((150, 280), "POST to /api/push_image", font=font_med, fill=0)

    # ==========================================
    # PAGE 2: PRODUCTIVITY
    # ==========================================
    elif page == 2:
        if mode == 1: # Todoist Tasks
            draw_red.text((40, 40), "TODAY'S TASKS", font=font_large, fill=0)
            todoist_key = state.get('todoist_api_key', '')
            tasks = get_todoist_tasks(todoist_key)
            
            y_offset = 120
            for i, task in enumerate(tasks):
                draw_layer = draw_red if (task.get('priority') == 4 or task.get('is_overdue')) else draw_black
                task_text = f"{i+1}. {task['content'][:35]}..." if len(task['content']) > 35 else f"{i+1}. {task['content']}"
                draw_layer.text((40, y_offset), task_text, font=font_med, fill=0)
                y_offset += 50
                
        elif mode == 2: # Calendar Agenda
            draw_red.text((40, 40), "TODAY'S AGENDA", font=font_large, fill=0)
            ical_url = state.get('calendar_ical_url', '')
            if ical_url=='':ical_url='https://ics.calendarlabs.com/33/0ff71705/India_Holidays.ics'
            events = get_calendar_events(ical_url)
            
            y_offset = 120
            for event in events:
                draw_red.text((40, y_offset), f"{event['time']}", font=font_med, fill=0)
                title = event['title'][:40] + "..." if len(event['title']) > 40 else event['title']
                draw_black.text((220, y_offset), title, font=font_med, fill=0)
                y_offset += 55
                
        elif mode == 3: # Scratchpad Notes (Markdown Supported)
            # Remove the hardcoded "NOTES" title so the user has full control of the canvas
            note_text = state.get('scratchpad_text', '')
            if note_text=='':note_text='# Welcome\nAdd **Markdown** notes via the Web UI!\n\n* Supports lists\n* And headers!'
            y_offset = 40 # Start higher up since we removed the hardcoded header
            lines = note_text.split('\n')
            
            for line in lines:
                line = line.strip()
                
                # Stop drawing if we are about to fall off the bottom of the screen (480px)
                if y_offset > 440:
                    break 
                    
                # Handle empty lines (spacing)
                if not line:
                    y_offset += 25
                    continue
                    
                # --- H1 HEADER (#) ---
                if line.startswith('# '):
                    text = line[2:]
                    # Draw H1 in bold RED
                    draw_red.text((40, y_offset), text, font=font_large, fill=0)
                    y_offset += 70
                    
                # --- H2 HEADER (##) ---
                elif line.startswith('## '):
                    text = line[3:]
                    # Draw H2 in bold BLACK
                    draw_black.text((40, y_offset), text, font=font_large, fill=0)
                    y_offset += 65
                    
                # --- BULLET POINTS (- or *) ---
                elif line.startswith('- ') or line.startswith('* '):
                    text = line[2:]
                    # Draw a red bullet point
                    draw_red.text((40, y_offset), "•", font=font_med, fill=0)
                    
                    # Wrap the text so long bullet points don't go off the right edge
                    wrapped = textwrap.wrap(text, width=45)
                    for w in wrapped:
                        draw_black.text((75, y_offset), w, font=font_med, fill=0)
                        y_offset += 45
                        if y_offset > 440: break
                        
                # --- STANDARD TEXT ---
                else:
                    # Clean up basic bolding syntax (**text**) by just rendering it normally for now
                    # (To actually change font weight mid-sentence in PIL requires complex bounding box math)
                    clean_line = line.replace('**', '').replace('__', '')
                    
                    # Smart word-wrapping 
                    wrapped = textwrap.wrap(clean_line, width=50)
                    for w in wrapped:
                        draw_black.text((40, y_offset), w, font=font_med, fill=0)
                        y_offset += 45
                        if y_offset > 440: break

    # ==========================================
    # PAGE 3: THE ART GALLERY
    # ==========================================
    elif page == 3:
        if mode ==1: # Single Photo or Local Slideshow
            path_b = os.path.join(UPLOAD_DIR, 'black_layer.bmp')
            path_r = os.path.join(UPLOAD_DIR, 'red_layer.bmp')
            if state.get('has_photo') and os.path.exists(path_b) and os.path.exists(path_r):
                img_black.paste(Image.open(path_b), (0,0))
                img_red.paste(Image.open(path_r), (0,0))
            else:
                draw_red.text((150, 200), "NO PHOTO UPLOADED", font=font_large, fill=0)
                draw_black.text((150, 280), "Use Web UI to upload media", font=font_med, fill=0)
        
        elif mode == 2: # Local Slideshow (Pre-baked E-ink format)
            slideshow_dir = os.path.join(UPLOAD_DIR, 'slideshow')
            
            # Find all pre-processed black layers
            import glob
            search_pattern = os.path.join(slideshow_dir, '*_black.bmp')
            slide_files = sorted(glob.glob(search_pattern))
            
            if slide_files:
                # Ensure our index is safely within bounds
                idx = state.get('slideshow_index', 0)
                if idx >= len(slide_files):
                    idx = 0
                    state['slideshow_index'] = 0
                    
                path_b = slide_files[idx]
                path_r = path_b.replace('_black.bmp', '_red.bmp') # Match the pair
                
                print(f"[*] Rendering Slide {idx + 1}/{len(slide_files)}: {os.path.basename(path_b)}")
                
                if os.path.exists(path_b) and os.path.exists(path_r):
                    img_black.paste(Image.open(path_b), (0,0))
                    img_red.paste(Image.open(path_r), (0,0))
            else:
                draw_red.text((150, 200), "SLIDESHOW FOLDER EMPTY", font=font_large, fill=0)
                draw_black.text((150, 280), "Upload images via Web UI", font=font_med, fill=0)
                
        elif mode == 3: # Picture of the Day
            potd_source = state.get('potd_source', 'nasa') 
            api_key = state.get('unsplash_api_key', '') if potd_source == 'unsplash' else ''
            
            potd_meta = get_picture_of_the_day(source=potd_source, api_key=api_key, upload_dir=POTD_DIR)
            path_b = os.path.join(POTD_DIR, 'black_layer.bmp')
            path_r = os.path.join(POTD_DIR, 'red_layer.bmp')
            
            if "error" not in potd_meta and os.path.exists(path_b) and os.path.exists(path_r):
                img_black.paste(Image.open(path_b), (0,0))
                img_red.paste(Image.open(path_r), (0,0))
                
                # Draw a white box with black text for the photo credit
                draw_black.rectangle([(0, 440), (800, 480)], fill=255)
                draw_black.text((10, 445), f"{potd_meta['title']} - {potd_meta['credit']}", font=font_small, fill=0)
            else:
                draw_red.text((150, 200), f"POTD ERROR: {potd_source.upper()}", font=font_large, fill=0)
                draw_black.text((150, 280), potd_meta.get("error", "Unknown Error"), font=font_med, fill=0)

    # Finally, push the deep refresh
    push_full_update(img_black, img_red)

# --- HARDWARE LOOP ---
def hardware_loop():
    global flag_full_refresh, flag_partial_refresh, partial_bbox
    
    last_drawn_time = ""
    last_full_refresh_time = time.time()
    last_slide_change_time= time.time()
    font_large, font_med, font_small = load_fonts()
    
    while True:
        now_str = datetime.now().strftime("%I:%M %p")
        sensor_data = get_sensor_data(dht_sensor)
        time_since_full = time.time() - last_full_refresh_time
        time_since_slide = time.time() - last_slide_change_time

        is_slideshow_active = (state.get('active_page') == 3 and state.get('active_mode') == 2)
        slide_interval = state.get('slideshow_interval', 3600) # Default 1 hour
        
        is_quotes_active = (state.get('active_page') == 1 and state.get('active_mode') == 2)

        if is_slideshow_active and time_since_slide >= slide_interval:
            print("[*] Auto-advancing slideshow...")
            state['slideshow_index'] = state.get('slideshow_index', 0) + 1
            save_state(state)
            flag_full_refresh = True
            last_slide_change_time = time.time()

        if is_quotes_active and time_since_slide >= slide_interval:
            flag_full_refresh=True
        
        # 1. API Push Partial Update (Page 1, Mode 3 B&W Diff)
        if flag_partial_refresh and partial_bbox:
            print(f"[*] Executing targeted API partial update for box: {partial_bbox}")
            api_img_path = os.path.join(UPLOAD_DIR, 'api_current.bmp')
            if os.path.exists(api_img_path):
                img_black = Image.open(api_img_path).convert('1').resize((800, 480))
                push_partial_update(img_black, *partial_bbox)
                
            flag_partial_refresh = False
            partial_bbox = None
            last_drawn_time = now_str # Prevent the clock from interfering

        # 2. Full Refresh (Button presses, page swaps, forced clears, or 1hr timeout)
        elif flag_full_refresh or time_since_full > 3600:
            print(f"[*] Dispatching FULL refresh. Page: {state['active_page']} | Mode: {state.get('active_mode', 1)}")
            render_current_state(now_str, sensor_data)
            
            flag_full_refresh = False
            last_drawn_time = now_str
            last_full_refresh_time = time.time()
            
        # 3. Targeted Clock Partial Update
        elif state['active_page'] == 1 and state.get('active_mode', 1) == 1 and now_str != last_drawn_time and not flag_full_refresh:
            print(f"[*] Fast partial update for clock tick: {now_str}")
            
            img_black_temp, _ = create_blank_layers()
            draw_temp = ImageDraw.Draw(img_black_temp)

            tz_configs = [
                    {"name": state.get('tz1_name', 'CEST'), "tz": state.get('tz1_zone', 'Europe/Paris')},
                    {"name": state.get('tz2_name', 'NY'), "tz": state.get('tz2_zone', 'America/New_York')},
                    {"name": state.get('tz3_name', 'TYO'), "tz": state.get('tz3_zone', 'Asia/Tokyo')}
                ]
            clocks = get_world_clocks(tz_configs)
            
            # The new unified clock bounding box (X1: 40, Y1: 60, X2: 400, Y2: 150)
            lbbox = (40, 60, 400, 150)
            tbbox = (80, 260, 420, 460)
            
            # Wipe the box clean (fill with 255/White) so the old time is erased
            draw_temp.rectangle(lbbox, fill=255) 
            draw_temp.text((40, 60), now_str, font=font_large, fill=0)

            y_offset = 260
            for clock in clocks['additional']:
                draw_temp.text((80, y_offset), f"{clock['name'].upper()}: {clock['time']}", font=font_med, fill=0)
                y_offset += 60
                
            push_partial_update(img_black_temp, *tbbox)

            # Push ONLY the specific box to the screen using our absolute coordinates
            push_partial_update(img_black_temp, *lbbox)
            last_drawn_time = now_str

        # Local time update on Quotes
        elif is_quotes_active and now_str != last_drawn_time and not flag_full_refresh:
            img_black_temp, _ = create_blank_layers()
            draw_temp = ImageDraw.Draw(img_black_temp)
            draw_temp.text((40, 440), f"Local: {now_str}", font=font_small, fill=0)
            lbbox = (40, 440, 200, 510) 
            push_partial_update(img_black_temp, *lbbox)
            last_drawn_time = now_str
        
            
        time.sleep(1)

if __name__ == '__main__':
    setup_gpio()
    zc, info = register_mdns()

    # Create the Flask App and pass in our state and thread-safe triggers
    app = create_app(state, trigger_full_refresh, trigger_partial_refresh)
    
    # Run Flask in a daemonized background thread so it doesn't block the hardware loop
    web_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False))
    web_thread.daemon = True
    web_thread.start()
    
    try:
        print("[*] Starting main hardware loop...")
        hardware_loop()
    except KeyboardInterrupt:
        print("[!] Shutting down...")
        zc.unregister_service(info)
        zc.close()
        GPIO.cleanup()