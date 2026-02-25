import os
import time
import json
import threading
from datetime import datetime
import subprocess
import socket
import board
import adafruit_dht
import RPi.GPIO as GPIO
from flask import Flask, render_template, request, redirect, url_for
from PIL import Image, ImageDraw, ImageFont
from zeroconf import IPVersion, ServiceInfo, Zeroconf

# Import the V2 Driver
from driver.epd7in5b_V2 import EPD

# Ensure time is handled correctly for your region
os.environ['TZ'] = 'Asia/Kolkata'
time.tzset()

# --- CONFIGURATION & STATE ---
UPLOAD_DIR = 'uploads'
STATE_FILE = 'state.json'
os.makedirs(UPLOAD_DIR, exist_ok=True)

state = {
    "active_page": 1,
    "calendar_source": "todoist",
    "has_photo": False,
    "wifi_msg": "",
    "is_rebooting": False
}

needs_refresh = True 
app = Flask(__name__)

# --- WI-FI MANAGEMENT FUNCTIONS ---
def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode

def setup_new_wifi(ssid, password):
    run_cmd(f'sudo nmcli connection delete "{ssid}"')
    c1 = run_cmd(f'sudo nmcli connection add type wifi ifname wlan0 con-name "{ssid}" ssid "{ssid}"')
    c2 = run_cmd(f'sudo nmcli connection modify "{ssid}" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "{password}"')
    c3 = run_cmd(f'sudo nmcli connection modify "{ssid}" connection.autoconnect-retries 3')
    return c1 == 0 and c2 == 0 and c3 == 0

def ensure_fallback_ap():
    if run_cmd('nmcli connection show "Fallback_AP"') != 0:
        run_cmd('sudo nmcli connection add type wifi ifname wlan0 mode ap con-name "Fallback_AP" ssid "Inky_Hotspot"')
        run_cmd('sudo nmcli connection modify "Fallback_AP" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "SecurePass123" ipv4.method shared')
    run_cmd('sudo nmcli connection modify "Fallback_AP" connection.autoconnect yes connection.autoconnect-priority -10')

def delayed_reboot(msg="Rebooting..."):
    global needs_refresh
    state['is_rebooting'] = True
    needs_refresh = True # Trigger one last draw to show rebooting status
    time.sleep(5)
    os.system('sudo reboot')

def register_mdns():
    """Registers Inky.local on the network"""
    desc = {'path': '/'}
    
    # Automatically get the Pi's local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    info = ServiceInfo(
        "_http._tcp.local.",
        "Inky._http._tcp.local.",
        addresses=[socket.inet_aton(local_ip)],
        port=5000,
        properties=desc,
        server="Inky.local.",
    )

    zc = Zeroconf(ip_version=IPVersion.V4Only)
    print(f"[*] Registering mDNS: Inky.local at {local_ip}")
    zc.register_service(info)
    return zc, info

# --- HARDWARE SETUP ---
DHT_PIN = board.D5
try:
    dht_sensor = adafruit_dht.DHT11(DHT_PIN) 
except Exception:
    pass 

BTN_PAGE_1 = 6
BTN_PAGE_2 = 13
BTN_PAGE_3 = 19
BTN_EXTRA  = 26

def setup_gpio():
    print("[*] Setting up GPIO buttons...", flush=True)
    try:
        GPIO.setmode(GPIO.BCM)
    except Exception:
        pass
        
    buttons = [BTN_PAGE_1, BTN_PAGE_2, BTN_PAGE_3, BTN_EXTRA]
    for btn in buttons:
        try:
            GPIO.setup(btn, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            # Remove any lingering edge detection from previous runs
            GPIO.remove_event_detect(btn) 
            
            # Attach the new interrupt
            GPIO.add_event_detect(btn, GPIO.FALLING, callback=button_callback, bouncetime=200)
            print(f"[+] Successfully attached interrupt to GPIO {btn}", flush=True)
        except Exception as e:
            print(f"[-] FAILED to attach interrupt to GPIO {btn}: {e}", flush=True)

def button_callback(channel):
    global needs_refresh
    
    # Force a print IMMEDIATELY when the hardware interrupt fires
    print(f"[HW] Interrupt fired on pin {channel}", flush=True)

    # Lowered debounce from 50ms to 10ms. 
    # This is fast enough to catch a quick tap, but slow enough to filter electrical noise.
    time.sleep(0.01)
    
    if GPIO.input(channel) != GPIO.LOW:
        print(f"[IGNORED] Pin {channel} was a ghost trigger/bounce.", flush=True)
        return 
        
    print(f"[VALID] Button press registered on GPIO {channel}", flush=True)

    if channel == BTN_PAGE_3:
        start_time = time.time()
        # Wait while button is held
        while GPIO.input(channel) == GPIO.LOW:
            time.sleep(0.1)
            if time.time() - start_time > 3.0:
                print("Long press detected: Triggering Reboot...", flush=True)
                threading.Thread(target=delayed_reboot).start()
                return

        # If released before 3s, it's just a normal page switch
        state['active_page'] = 3

    if channel == BTN_PAGE_1: state['active_page'] = 1
    elif channel == BTN_PAGE_2: state['active_page'] = 2
    elif channel == BTN_EXTRA: pass 
    
    save_state()
    needs_refresh = True

# --- STATE MANAGEMENT ---
def load_state():
    global state
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            saved = json.load(f)
            saved['wifi_msg'] = ""
            saved['is_rebooting'] = False
            state.update(saved)

def save_state():
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

# --- IMAGE PROCESSING (V2: Split into Black & Red Layers) ---
def process_upload(filepath):
    """ Converts uploaded RGB image into two separate 1-bit BMPs for the V2 display """
    img = Image.open(filepath).resize((800, 480)).convert("RGB")
    
    # Quantize to 3 colors
    palettedata = [255, 255, 255,  0, 0, 0,  255, 0, 0] # White, Black, Red
    palettedata.extend([0] * (768 - len(palettedata)))
    palimage = Image.new('P', (1, 1))
    palimage.putpalette(palettedata)
    img_converted = img.quantize(palette=palimage)
    
    # Create the two blank 1-bit layers (255 = White background)
    img_black = Image.new('1', (800, 480), 255)
    img_red = Image.new('1', (800, 480), 255)
    
    p_black = img_black.load()
    p_red = img_red.load()
    p_old = img_converted.load()
    
    # Map pixels to layers
    for y in range(480):
        for x in range(800):
            if p_old[x, y] == 1: p_black[x,y] = 0   # Draw to Black Layer
            elif p_old[x, y] == 2: p_red[x,y] = 0   # Draw to Red Layer
            
    img_black.save(os.path.join(UPLOAD_DIR, 'black_layer.bmp'))
    img_red.save(os.path.join(UPLOAD_DIR, 'red_layer.bmp'))

# --- WEB SERVER ROUTES ---
@app.route('/', methods=['GET', 'POST'])
def index():
    global needs_refresh
    if request.method == 'POST':
        action = request.form.get('action')
        state['wifi_msg'] = "" # Clear previous messages
        
        if action == 'set_page':
            state['active_page'] = int(request.form.get('page'))
        elif action == 'set_source':
            state['calendar_source'] = request.form.get('source')
        elif action == 'upload':
            file = request.files.get('image')
            if file:
                temp_path = os.path.join(UPLOAD_DIR, 'temp.jpg')
                file.save(temp_path)
                process_upload(temp_path)
                state['has_photo'] = True
                state['active_page'] = 3
        elif action == 'set_wifi':
            ssid = request.form.get('ssid')
            password = request.form.get('password')
            if ssid and password:
                success = setup_new_wifi(ssid, password)
                ensure_fallback_ap()
                if success:
                    state['wifi_msg'] = f"Success! Added '{ssid}'. Rebooting device now..."
                    threading.Thread(target=delayed_reboot).start()
                else:
                    state['wifi_msg'] = "Error applying Wi-Fi settings."
        elif action == 'reboot':
            threading.Thread(target=delayed_reboot).start()
                
        save_state()
        needs_refresh = True
        return redirect(url_for('index'))
        
    return render_template('index.html', state=state)

# --- HARDWARE DISPLAY LOOP ---
def get_sensor_string():
    sensor_str = "Sensor Error"
    for _ in range(3):
        try:
            temp = dht_sensor.temperature
            hum = dht_sensor.humidity
            if temp is not None and hum is not None:
                return f"Temp: {temp}C  |  Hum: {hum}%"
        except Exception:
            time.sleep(1.0)
    return sensor_str

def load_fonts():
    try:
        return ImageFont.truetype("fonts/roboto/Roboto-Black.ttf", 64), ImageFont.truetype("fonts/roboto/Roboto-Regular.ttf", 36)
    except Exception:
        return ImageFont.load_default(), ImageFont.load_default()

def draw_partial_update(time_str, sensor_str):
    """Blazing fast update of ONLY the clock and sensor bounding boxes"""
    epd = EPD()
    epd.init_part()
    font_large, font_med = load_fonts()

    # 1. Update Clock Box (X: 0->800, Y: 40->160)
    img_clock = Image.new('1', (800, 120), 255)
    draw_clock = ImageDraw.Draw(img_clock)
    draw_clock.text((40, 60 - 40), time_str, font=font_large, fill=0)
    epd.display_Partial(epd.getbuffer(img_clock), 0, 40, 800, 160)

    # 2. Update Sensor Box (X: 0->800, Y: 380->480)
    img_sensor = Image.new('1', (800, 100), 255)
    draw_sensor = ImageDraw.Draw(img_sensor)
    draw_sensor.text((40, 400 - 380), sensor_str, font=font_med, fill=0)
    epd.display_Partial(epd.getbuffer(img_sensor), 0, 380, 800, 480)

    epd.sleep()

def draw_full_update(time_str, sensor_str):
    """Deep flush of the entire screen to clear ghosting and draw full colors"""
    epd = EPD()
    epd.init()
    
    image_black = Image.new('1', (800, 480), 255) 
    image_red = Image.new('1', (800, 480), 255) 
    draw_black, draw_red = ImageDraw.Draw(image_black), ImageDraw.Draw(image_red)
    font_large, font_med = load_fonts()
    
    if state.get('is_rebooting'):
        draw_red.text((200, 200), "REBOOTING...", font=font_large, fill=0)
        draw_black.text((200, 280), "Please wait 60 seconds", font=font_med, fill=0)
    else:
        page = state['active_page']
        if page == 1:
            draw_black.text((40, 60), time_str, font=font_large, fill=0) 
            draw_red.text((40, 160), datetime.now().strftime("%A, %B %d"), font=font_med, fill=0) 
            draw_black.text((40, 400), sensor_str, font=font_med, fill=0)
            
        elif page == 2:
            source = state['calendar_source'].upper()
            draw_red.text((40, 40), f"{source} TASKS", font=font_large, fill=0) 
            draw_black.text((40, 140), "1. Example Task 1", font=font_med, fill=0)
            draw_black.text((40, 200), "2. Example Task 2", font=font_med, fill=0)
            draw_black.text((40, 400), sensor_str, font=font_med, fill=0)
            
        elif page == 3:
            path_b, path_r = os.path.join(UPLOAD_DIR, 'black_layer.bmp'), os.path.join(UPLOAD_DIR, 'red_layer.bmp')
            if state['has_photo'] and os.path.exists(path_b) and os.path.exists(path_r):
                image_black.paste(Image.open(path_b), (0,0))
                image_red.paste(Image.open(path_r), (0,0))
            else:
                draw_red.text((150, 200), "NO PHOTO UPLOADED", font=font_large, fill=0)
            
    epd.display(epd.getbuffer(image_black), epd.getbuffer(image_red))
    epd.sleep()

def hardware_loop():
    global needs_refresh
    last_drawn_page = None
    last_drawn_time = None
    last_full_refresh_time = 0
    
    while True:
        now_str = datetime.now().strftime("%I:%M %p")
        sensor_str = get_sensor_string()
        time_since_full = time.time() - last_full_refresh_time
        
        # Determine if we MUST do a slow, full refresh (Page swap, forced refresh, or 1 hour passed to clear ghosting)
        if needs_refresh or state['active_page'] != last_drawn_page or time_since_full > 3600:
            print(f"[*] Dispatching FULL refresh. Page: {state['active_page']}")
            draw_full_update(now_str, sensor_str)
            
            last_drawn_page = state['active_page']
            last_drawn_time = now_str
            last_full_refresh_time = time.time()
            needs_refresh = False
            
        # Determine if we can do a blazing-fast partial refresh (Only on Page 1, only if the minute ticked)
        elif state['active_page'] == 1 and now_str != last_drawn_time:
            print(f"[*] Dispatching PARTIAL update for time: {now_str}")
            draw_partial_update(now_str, sensor_str)
            last_drawn_time = now_str
            
        time.sleep(1)

if __name__ == '__main__':
    load_state()
    setup_gpio()
      
    zc, info = register_mdns()

    web_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False))
    web_thread.daemon = True
    web_thread.start()
    
    try:
        hardware_loop()
    except KeyboardInterrupt:
        zc.unregister_service(info)
        zc.close()
        GPIO.cleanup()