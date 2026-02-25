import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
from utils import save_state, setup_new_wifi, ensure_fallback_ap, process_upload, calculate_bw_diff

UPLOAD_DIR = 'uploads'
os.makedirs(UPLOAD_DIR, exist_ok=True)

def create_app(state_ref, trigger_full_refresh, trigger_partial_refresh):
    """
    App factory pattern. 
    Receives the shared state dictionary and callback functions from main.py 
    so Flask can trigger screen updates safely on the main hardware thread.
    """
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16MB max upload

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

    @app.route('/api/push_image', methods=['POST'])
    def api_push_image():
        """
        The dedicated endpoint for Page 1, Mode 3 (Custom B&W API Push).
        Expects a B&W image file. Calculates the diff and triggers a partial update.
        """
        # Security check: Ensure we are actually on the right page/mode to receive this
        if state_ref['active_page'] != 1 or state_ref['active_mode'] != 3:
            return jsonify({"error": "Device is not currently in API Push mode (Page 1, Mode 3)."}), 403

        if 'image' not in request.files:
            return jsonify({"error": "No image provided"}), 400
            
        file = request.files['image']
        new_image_path = os.path.join(UPLOAD_DIR, 'api_new.bmp')
        old_image_path = os.path.join(UPLOAD_DIR, 'api_current.bmp')
        
        file.save(new_image_path)
        
        # If this is the first ever push, we need a full refresh to set the baseline
        if not os.path.exists(old_image_path):
            os.rename(new_image_path, old_image_path)
            trigger_full_refresh()
            return jsonify({"status": "success", "update_type": "full_refresh_baseline"})

        # Calculate the B&W difference
        bbox, _ = calculate_bw_diff(old_image_path, new_image_path)
        
        if not bbox:
            return jsonify({"status": "success", "update_type": "none", "message": "Images are identical."})
            
        # Move new image to current
        os.replace(new_image_path, old_image_path)
        
        # Check for force_full override in the request
        if request.form.get('force_full', 'false').lower() == 'true':
            trigger_full_refresh()
            return jsonify({"status": "success", "update_type": "full_refresh_forced"})
            
        # Tell the main thread to execute a partial update with these exact coordinates!
        trigger_partial_refresh(bbox)
        
        return jsonify({
            "status": "success", 
            "update_type": "partial", 
            "bounding_box": bbox
        })

    return app