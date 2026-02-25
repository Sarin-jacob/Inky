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
        port=80,
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
    try:
        GPIO.setmode(GPIO.BCM)
    except Exception:
        pass
        
    buttons = [BTN_PAGE_1, BTN_PAGE_2, BTN_PAGE_3, BTN_EXTRA]
    for btn in buttons:
        GPIO.setup(btn, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # Increased bouncetime to 1000ms to help with the ghost triggering
        try:
            GPIO.add_event_detect(btn, GPIO.FALLING, callback=button_callback, bouncetime=200)
        except RuntimeError:
            pass

def button_callback(channel):
    global needs_refresh
    
    # Software Debounce: Wait 50ms and check if the button is STILL pressed.
    # This filters out electrical noise jumping between pins 6 and 13.
    time.sleep(0.05)
    if GPIO.input(channel) != GPIO.LOW:
        return # It was a ghost trigger, ignore it
        
    print(f"Valid button press detected on GPIO {channel}")

    if channel == BTN_PAGE_3:
        start_time = time.time()
        # Wait while button is held
        while GPIO.input(channel) == GPIO.LOW:
            time.sleep(0.1)
            if time.time() - start_time > 3.0:
                print("Long press detected: Triggering Reboot...")
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
def draw_display():
    epd = EPD()
    epd.init()
    
    # V2 requires TWO images
    image_black = Image.new('1', (800, 480), 255) 
    image_red = Image.new('1', (800, 480), 255) 
    
    draw_black = ImageDraw.Draw(image_black)
    draw_red = ImageDraw.Draw(image_red)
    
    try:
        font_large = ImageFont.truetype("fonts/roboto/Roboto-Black.ttf", 64)
        font_med = ImageFont.truetype("fonts/roboto/Roboto-Regular.ttf", 36)
    except Exception:
        font_large = ImageFont.load_default()
        font_med = ImageFont.load_default()
    
    if state.get('is_rebooting'):
        draw_red.text((200, 200), "REBOOTING...", font=font_large, fill=0)
        draw_black.text((200, 280), "Please wait 60 seconds", font=font_med, fill=0)
    else:
        # Sensor Reading
        try:
            temp = dht_sensor.temperature
            hum = dht_sensor.humidity
            sensor_str = f"Temp: {temp}C  |  Hum: {hum}%" if temp else "Sensor Data Unavailable"
        except Exception:
            sensor_str = "Sensor Error"

        page = state['active_page']
        
        if page == 1:
            # PAGE 1: Clock & Calendar
            now = datetime.now()
            draw_black.text((40, 60), now.strftime("%I:%M %p"), font=font_large, fill=0) 
            draw_red.text((40, 160), now.strftime("%A, %B %d"), font=font_med, fill=0) 
            draw_black.text((40, 400), sensor_str, font=font_med, fill=0)
            
        elif page == 2:
            # PAGE 2: Todoist / Google Cal 
            source = state['calendar_source'].upper()
            draw_red.text((40, 40), f"{source} TASKS", font=font_large, fill=0) 
            draw_black.text((40, 140), "1. Example Task 1", font=font_med, fill=0)
            draw_black.text((40, 200), "2. Example Task 2", font=font_med, fill=0)
            draw_black.text((40, 400), sensor_str, font=font_med, fill=0)
            
        elif page == 3:
            # PAGE 3: Photo Viewer
            path_b = os.path.join(UPLOAD_DIR, 'black_layer.bmp')
            path_r = os.path.join(UPLOAD_DIR, 'red_layer.bmp')
            
            if state['has_photo'] and os.path.exists(path_b) and os.path.exists(path_r):
                bmp_black = Image.open(path_b)
                bmp_red = Image.open(path_r)
                image_black.paste(bmp_black, (0,0))
                image_red.paste(bmp_red, (0,0))
            else:
                draw_red.text((150, 200), "NO PHOTO UPLOADED", font=font_large, fill=0)
            
    # Send both layers to V2 driver
    epd.display(epd.getbuffer(image_black), epd.getbuffer(image_red))
    epd.sleep()

def hardware_loop():
    global needs_refresh
    last_refresh_time = time.time()
    
    while True:
        time_elapsed = time.time() - last_refresh_time
        # Auto-refresh Page 1 every 5 minutes
        if needs_refresh or (state['active_page'] == 1 and time_elapsed > 300):
            print("Refreshing display...")
            try:
                draw_display()
            except Exception as e:
                print(f"Draw Error: {e}")
            needs_refresh = False
            last_refresh_time = time.time()
            
        time.sleep(1) 

if __name__ == '__main__':
    load_state()
    setup_gpio()
      
    zc, info = register_mdns()

    web_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=80, debug=False, use_reloader=False))
    web_thread.daemon = True
    web_thread.start()
    
    try:
        hardware_loop()
    except KeyboardInterrupt:
        zc.unregister_service(info)
        zc.close()
        GPIO.cleanup()