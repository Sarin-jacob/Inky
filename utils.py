import os
import json
import subprocess
import socket
from PIL import Image, ImageChops
from zeroconf import IPVersion, ServiceInfo, Zeroconf

# --- STATE MANAGEMENT ---
def load_state(filepath="state.json"):
    """Loads the current state, ensuring volatile flags are reset."""
    default_state = {
        "active_page": 1,
        "active_mode": 1,
        "calendar_source": "todoist",
        "has_photo": False,
        "wifi_msg": "",
        "is_rebooting": False
    }
    
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                saved = json.load(f)
                default_state.update(saved)
        except Exception as e:
            print(f"[-] Error loading state: {e}")
            
    # Always reset volatile flags on boot
    default_state['wifi_msg'] = ""
    default_state['is_rebooting'] = False
    return default_state

def save_state(state, filepath="state.json"):
    """Saves the current state to disk."""
    with open(filepath, 'w') as f:
        json.dump(state, f)

# --- WI-FI & NETWORK MANAGEMENT ---
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

def register_mdns():
    """Registers Inky.local on the network"""
    desc = {'path': '/'}
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

# --- IMAGE PROCESSING ---
def process_upload(filepath, upload_dir='uploads'):
    """Converts uploaded RGB image into two separate 1-bit BMPs for the V2 display (3-color palette)."""
    os.makedirs(upload_dir, exist_ok=True)
    img = Image.open(filepath).resize((800, 480)).convert("RGB")
    
    # Quantize to 3 colors: White, Black, Red
    palettedata = [255, 255, 255,  0, 0, 0,  255, 0, 0] 
    palettedata.extend([0] * (768 - len(palettedata)))
    palimage = Image.new('P', (1, 1))
    palimage.putpalette(palettedata)
    img_converted = img.quantize(palette=palimage)
    
    img_black = Image.new('1', (800, 480), 255)
    img_red = Image.new('1', (800, 480), 255)
    
    p_black, p_red = img_black.load(), img_red.load()
    p_old = img_converted.load()
    
    for y in range(480):
        for x in range(800):
            if p_old[x, y] == 1: p_black[x,y] = 0   # Draw to Black Layer
            elif p_old[x, y] == 2: p_red[x,y] = 0   # Draw to Red Layer
            
    img_black.save(os.path.join(upload_dir, 'black_layer.bmp'))
    img_red.save(os.path.join(upload_dir, 'red_layer.bmp'))

def calculate_bw_diff(old_image_path, new_image_path):
    """
    Compares two B&W images and returns the bounding box of the differences.
    Perfect for targeted partial updates without red-layer ghosting.
    Returns: (bbox, new_image_object)
    """
    try:
        old_img = Image.open(old_image_path).convert('1').resize((800, 480))
        new_img = Image.open(new_image_path).convert('1').resize((800, 480))
        
        diff = ImageChops.difference(old_img, new_img)
        bbox = diff.getbbox()  # Returns (left, upper, right, lower) or None
        
        return bbox, new_img
    except Exception as e:
        print(f"[-] Diff engine error: {e}")
        return None, None