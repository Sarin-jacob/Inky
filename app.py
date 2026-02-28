import os
import time
import glob
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, jsonify,send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from utils import save_state, setup_new_wifi, ensure_fallback_ap, process_upload, calculate_bw_diff


UPLOAD_DIR = 'uploads'
os.makedirs(UPLOAD_DIR, exist_ok=True)

SLIDESHOW_DIR = os.path.join(UPLOAD_DIR, 'slideshow')
os.makedirs(SLIDESHOW_DIR, exist_ok=True)

QUOTES_DIR = os.path.join(UPLOAD_DIR, 'quotes')
os.makedirs(QUOTES_DIR, exist_ok=True)

def create_app(state_ref, trigger_full_refresh, trigger_partial_refresh):
    """
    App factory pattern. 
    Receives the shared state dictionary and callback functions from main.py 
    so Flask can trigger screen updates safely on the main hardware thread.
    """
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16MB max upload
    CORS(app)

    @app.route('/', methods=['GET', 'POST'])
    def index():
        if request.method == 'POST':
            action = request.form.get('action')
            state_ref['wifi_msg'] = "" 
            
            if action == 'set_page':
                state_ref['active_page'] = int(request.form.get('page'))
                state_ref['active_mode'] = 1
                trigger_full_refresh()

            elif action == 'set_mode':
                state_ref['active_mode'] = int(request.form.get('mode'))
                trigger_full_refresh()

            elif action == 'reboot':
                state_ref['is_rebooting'] = True
                trigger_full_refresh()
                # main.py handles the actual os.system reboot based on this flag
                
            elif action == 'set_wifi':
                ssid = request.form.get('ssid')
                password = request.form.get('password')
                if ssid and password:
                    success = setup_new_wifi(ssid, password)
                    ensure_fallback_ap()
                    if success:
                        state_ref['wifi_msg'] = f"Success! Added '{ssid}'. Rebooting..."
                        state_ref['is_rebooting'] = True
                        trigger_full_refresh()
                    else:
                        state_ref['wifi_msg'] = "Error applying Wi-Fi settings."
            elif action == 'set_config':
                # Save all the new fields into the state dictionary
                if request.form.get('todoist_api_key'): state_ref['todoist_api_key'] = request.form.get('todoist_api_key').strip()
                if request.form.get('openweather_api_key'): state_ref['openweather_api_key'] = request.form.get('openweather_api_key').strip()
                if request.form.get('unsplash_api_key'): state_ref['unsplash_api_key'] = request.form.get('unsplash_api_key').strip()
                state_ref['potd_source'] = request.form.get('potd_source', 'nasa').strip()
                state_ref['calendar_ical_url'] = request.form.get('calendar_ical_url', '').strip()
                state_ref['scratchpad_text'] = request.form.get('scratchpad_text', '').strip()

                state_ref['tz1_name'] = request.form.get('tz1_name', 'CEST')
                state_ref['tz1_zone'] = request.form.get('tz1_zone', 'Europe/Paris')
                
                state_ref['tz2_name'] = request.form.get('tz2_name', 'NY')
                state_ref['tz2_zone'] = request.form.get('tz2_zone', 'America/New_York')
                
                state_ref['tz3_name'] = request.form.get('tz3_name', 'TYO')
                state_ref['tz3_zone'] = request.form.get('tz3_zone', 'Asia/Tokyo')

                trigger_full_refresh()

            save_state(state_ref)
            return redirect(url_for('index'))
            
        # For now, we'll return JSON if templates don't exist yet, just to test the API
        try:
            return render_template('index.html', state=state_ref)
        except Exception:
            return jsonify({"status": "Web UI active", "current_state": state_ref})

    @app.route('/media', methods=['POST'])
    def upload_media():
        """Handles manual photo uploads for Page 3 (The Art Gallery)"""
        if 'image' not in request.files:
            return redirect(url_for('index'))
            
        file = request.files['image']
        if file.filename != '':
            temp_path = os.path.join(UPLOAD_DIR, 'temp_upload.jpg')
            file.save(temp_path)
            process_upload(temp_path, UPLOAD_DIR)
            
            state_ref['has_photo'] = True
            state_ref['active_page'] = 3
            state_ref['active_mode'] = 1
            trigger_full_refresh()
            save_state(state_ref)
            
        return redirect(url_for('index'))
    
    @app.route('/api/slides/thumb/<slide_id>')
    def serve_thumb(slide_id):
        """Serves the tiny color thumbnail for the Web UI."""
        return send_from_directory(SLIDESHOW_DIR, f'{slide_id}_thumb.jpg')

    @app.route('/api/slides', methods=['GET'])
    def list_slides():
        """Returns a list of all pre-processed slides."""
        # Find all black layers, which represent a valid slide pair
        search_pattern = os.path.join(SLIDESHOW_DIR, '*_black.bmp')
        slides = [os.path.basename(f).replace('_black.bmp', '') for f in glob.glob(search_pattern)]
        return jsonify({
            "slides": sorted(slides),
            "interval_seconds": state_ref.get('slideshow_interval', 3600)
        })

    @app.route('/api/slides/upload', methods=['POST'])
    def upload_slide():
        """Uploads a new slide, generates a thumbnail, pre-processes it, and saves the pair."""
        if 'image' not in request.files:
            return redirect(url_for('index'))
            
        file = request.files['image']
        if file.filename != '':
            slide_id = str(int(time.time())) # Unique ID 
            
            temp_path = os.path.join(SLIDESHOW_DIR, f'temp_{slide_id}.jpg')
            file.save(temp_path)
            
            # --- NEW: Generate a tiny color thumbnail BEFORE palette processing ---
            try:
                img = Image.open(temp_path).convert("RGB")
                img.thumbnail((160, 96)) # Scaled perfectly to match the 800x480 screen aspect ratio
                img.save(os.path.join(SLIDESHOW_DIR, f'{slide_id}_thumb.jpg'))
            except Exception as e:
                print(f"[-] Error generating thumbnail: {e}")
            # -------------------------------------------------------------------
            
            # Process into e-ink palette
            process_upload(temp_path, SLIDESHOW_DIR)
            
            # Rename processed BMPs
            os.rename(os.path.join(SLIDESHOW_DIR, 'black_layer.bmp'), os.path.join(SLIDESHOW_DIR, f'{slide_id}_black.bmp'))
            os.rename(os.path.join(SLIDESHOW_DIR, 'red_layer.bmp'), os.path.join(SLIDESHOW_DIR, f'{slide_id}_red.bmp'))
            
            os.remove(temp_path)
            
            if state_ref.get('active_page') == 3 and state_ref.get('active_mode') == 2:
                state_ref['slideshow_index'] = 0
                trigger_full_refresh()
                
            save_state(state_ref)
            
        return redirect(url_for('index'))

    @app.route('/api/slides/delete/<slide_id>', methods=['POST'])
    def delete_slide(slide_id):
        """Deletes a pre-processed slide pair."""
        path_b = os.path.join(SLIDESHOW_DIR, f'{slide_id}_black.bmp')
        path_r = os.path.join(SLIDESHOW_DIR, f'{slide_id}_red.bmp')
        path_t = os.path.join(SLIDESHOW_DIR, f'{slide_id}_thumb.jpg')
        
        if os.path.exists(path_b): os.remove(path_b)
        if os.path.exists(path_r): os.remove(path_r)
        if os.path.exists(path_t): os.remove(path_t)
        
        # Reset index to prevent out-of-bounds errors on the hardware loop
        state_ref['slideshow_index'] = 0 
        save_state(state_ref)
        
        return jsonify({"status": "success", "deleted": slide_id})
    
    @app.route('/api/slides/interval', methods=['POST'])
    def set_slide_interval():
        """Updates the time between slides (in seconds)."""
        interval = int(request.form.get('interval', 3600))
        state_ref['slideshow_interval'] = interval
        save_state(state_ref)
        return redirect(url_for('index'))

    # --- QUOTES ENDPOINTS ---
    @app.route('/api/quotes', methods=['GET'])
    def list_quotes():
        """Lists all uploaded quote CSVs."""
        import glob
        csvs = [os.path.basename(f) for f in glob.glob(os.path.join(QUOTES_DIR, '*.csv'))]
        return jsonify({
            "active_csv": state_ref.get('active_quote_csv', ''),
            "available_csvs": sorted(csvs)
        })

    @app.route('/api/quotes/upload', methods=['POST'])
    def upload_quote_csv():
        if 'csv_file' not in request.files:
            return redirect(url_for('index'))
            
        file = request.files['csv_file']
        if file.filename != '' and file.filename.endswith('.csv'):
            # Secure the filename to prevent path traversal
            filename = secure_filename(file.filename)
            file.save(os.path.join(QUOTES_DIR, filename))
            
            # If no active CSV is set, make this one active automatically
            if not state_ref.get('active_quote_csv'):
                state_ref['active_quote_csv'] = filename
                
            save_state(state_ref)
        return redirect(url_for('index'))

    @app.route('/api/quotes/active', methods=['POST'])
    def set_active_csv():
        filename = request.form.get('filename')
        if filename:
            state_ref['active_quote_csv'] = filename
            state_ref['shown_quotes'] = [] # Reset the shown list when switching files!
            save_state(state_ref)
            
            # If we are currently looking at the quotes page, force a refresh
            if state_ref.get('active_page') == 1 and state_ref.get('active_mode') == 2:
                trigger_full_refresh()
                
        return redirect(url_for('index'))
        
    @app.route('/api/quotes/delete/<filename>', methods=['POST'])
    def delete_quote_csv(filename):
        safe_name = secure_filename(filename)
        path = os.path.join(QUOTES_DIR, safe_name)
        if os.path.exists(path):
            os.remove(path)
            # If we deleted the active one, clear the state
            if state_ref.get('active_quote_csv') == safe_name:
                state_ref['active_quote_csv'] = ""
            save_state(state_ref)
        return jsonify({"status": "success", "deleted": safe_name})

    @app.route('/api/push_image', methods=['POST'])
    def api_push_image():
        """
        The dedicated endpoint for Page 1, Mode 3 (Custom B&W API Push).
        Intercepts the upload, forces 800x480 B&W, and triggers a full-screen partial update.
        """
        if state_ref.get('active_page') != 1 or state_ref.get('active_mode') != 3:
            return jsonify({"error": "Device is not currently in API Push mode (Page 1, Mode 3)."}), 403

        if 'image' not in request.files:
            return jsonify({"error": "No image provided"}), 400
            
        file = request.files['image']
        current_image_path = os.path.join(UPLOAD_DIR, 'api_current.bmp')
        
        # Check if this is the first push before we overwrite the file
        is_first_push = not os.path.exists(current_image_path)
        
        try:
            # Force exactly 800x480 B&W format and overwrite the current image directly
            img = Image.open(file).convert('1').resize((800, 480))
            img.save(current_image_path, format='BMP')
        except Exception as e:
            return jsonify({"error": f"Failed to process image: {e}"}), 400
        
        # Check for force_full override OR if it's the very first image
        if request.form.get('force_full', 'false').lower() == 'true' or is_first_push:
            trigger_full_refresh()
            return jsonify({"status": "success", "update_type": "full_refresh"})
            
        # Tell the main thread to execute a partial update on the ENTIRE 800x480 canvas
        full_screen_bbox = (0, 0, 800, 480)
        trigger_partial_refresh(full_screen_bbox)
        
        return jsonify({
            "status": "success", 
            "update_type": "partial_fullscreen", 
            "bounding_box": full_screen_bbox
        })

    return app