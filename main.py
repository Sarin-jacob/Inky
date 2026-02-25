import os
import time
import threading
from datetime import datetime
import RPi.GPIO as GPIO
import board
import adafruit_dht
from PIL import Image, ImageDraw

# Import our new modular tools
from utils import load_state, save_state, register_mdns
from display import push_full_update, push_partial_update, get_sensor_string, create_blank_layers, load_fonts
from app import create_app

# --- CONFIGURATION & STATE ---
os.environ['TZ'] = 'Asia/Kolkata'
time.tzset()

UPLOAD_DIR = 'uploads'
os.makedirs(UPLOAD_DIR, exist_ok=True)

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
    if is_reboot_combo:
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
def render_current_state(time_str, sensor_str):
    """Builds the full screen image based on the current state."""
    img_black, img_red = create_blank_layers()
    draw_black, draw_red = ImageDraw.Draw(img_black), ImageDraw.Draw(img_red)
    font_large, font_med, font_small = load_fonts()
    
    page = state.get('active_page', 1)
    mode = state.get('active_mode', 1)

    if state.get('is_rebooting'):
        draw_red.text((250, 200), "REBOOTING...", font=font_large, fill=0)
        draw_black.text((260, 280), "Please wait 60 seconds.", font=font_med, fill=0)

    # --- PAGE 1: THE DAILY HUB ---
    elif page == 1:
        if mode == 1: # Minimalist Clock
            draw_black.text((40, 60), time_str, font=font_large, fill=0)
            draw_red.text((40, 160), datetime.now().strftime("%A, %B %d"), font=font_med, fill=0)
            draw_black.text((40, 400), sensor_str, font=font_med, fill=0)
            
        elif mode == 2: # World Clock / Weather (Layout scaffold)
            draw_black.text((40, 40), f"Local: {time_str}", font=font_med, fill=0)
            draw_black.text((40, 100), "CEST: --:-- --", font=font_small, fill=0) # Placeholder for timezone logic
            draw_red.text((40, 180), "WEATHER FORECAST", font=font_large, fill=0)
            draw_black.text((40, 260), "API Sync Pending...", font=font_med, fill=0)
            draw_black.text((40, 400), sensor_str, font=font_med, fill=0)
            
        elif mode == 3: # Custom API Push (B&W Only)
            api_img_path = os.path.join(UPLOAD_DIR, 'api_current.bmp')
            if os.path.exists(api_img_path):
                api_img = Image.open(api_img_path).convert('1').resize((800, 480))
                img_black.paste(api_img, (0, 0))
            else:
                draw_black.text((150, 200), "WAITING FOR API PUSH", font=font_large, fill=0)
                draw_black.text((150, 280), "POST to /api/push_image", font=font_med, fill=0)

    # --- PAGE 2: PRODUCTIVITY ---
    elif page == 2:
        source = state.get('calendar_source', 'todoist').upper()
        draw_red.text((40, 40), f"{source} TASKS (Mode {mode})", font=font_large, fill=0)
        draw_black.text((40, 140), "1. Connect API in Web UI", font=font_med, fill=0)
        draw_black.text((40, 200), "2. Parse JSON response", font=font_med, fill=0)
        draw_black.text((40, 400), sensor_str, font=font_med, fill=0)

    # --- PAGE 3: THE ART GALLERY ---
    elif page == 3:
        path_b = os.path.join(UPLOAD_DIR, 'black_layer.bmp')
        path_r = os.path.join(UPLOAD_DIR, 'red_layer.bmp')
        if state.get('has_photo') and os.path.exists(path_b) and os.path.exists(path_r):
            img_black.paste(Image.open(path_b), (0,0))
            img_red.paste(Image.open(path_r), (0,0))
        else:
            draw_red.text((150, 200), "NO PHOTO UPLOADED", font=font_large, fill=0)
            draw_black.text((150, 280), "Use Web UI to upload media", font=font_med, fill=0)

    push_full_update(img_black, img_red)

# --- HARDWARE LOOP ---
def hardware_loop():
    global flag_full_refresh, flag_partial_refresh, partial_bbox
    
    last_drawn_time = ""
    last_full_refresh_time = time.time()
    
    while True:
        now_str = datetime.now().strftime("%I:%M %p")
        sensor_str = get_sensor_string(dht_sensor)
        time_since_full = time.time() - last_full_refresh_time
        
        # 1. API Push Partial Update (Page 1, Mode 3 B&W Diff)
        if flag_partial_refresh and partial_bbox:
            print(f"[*] Executing targeted API partial update for box: {partial_bbox}")
            api_img_path = os.path.join(UPLOAD_DIR, 'api_current.bmp')
            if os.path.exists(api_img_path):
                img_black = Image.open(api_img_path).convert('1').resize((800, 480))
                # Unpack the bounding box tuple (x1, y1, x2, y2) into the function
                push_partial_update(img_black, *partial_bbox)
                
            flag_partial_refresh = False
            partial_bbox = None
            last_drawn_time = now_str # Prevent the clock from overriding this right away

        # 2. Full Refresh (Button presses, page swaps, forced clears, or 1hr timeout)
        elif flag_full_refresh or time_since_full > 3600:
            print(f"[*] Dispatching FULL refresh. Page: {state['active_page']} | Mode: {state.get('active_mode', 1)}")
            render_current_state(now_str, sensor_str)
            
            flag_full_refresh = False
            last_drawn_time = now_str
            last_full_refresh_time = time.time()
            
        # 3. Clock Partial Update (Only on Page 1 Mode 1/2 when the minute changes)
        elif state['active_page'] == 1 and state.get('active_mode', 1) in [1, 2] and now_str != last_drawn_time:
            # Note: You can expand this logic later to build a targeted black-layer partial 
            # update just for the clock bounding box, similar to how we did the API diff!
            # For now, we trigger a full update so the screen stays accurate.
            flag_full_refresh = True 
            
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