import os
import json
import time
import requests
from datetime import datetime
import shutil
from utils import process_upload
try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Fallback for older Python versions
    import pytz
    ZoneInfo = pytz.timezone

import urllib.request
from datetime import date
try:
    import icalendar
    import recurring_ical_events
except ImportError:
    icalendar = None

CACHE_DIR = 'cache'
os.makedirs(CACHE_DIR, exist_ok=True)

# --- CACHE MANAGEMENT ---
def get_cached_data(filename, max_age_seconds):
    """Returns cached data if it exists and is fresh, else returns None."""
    filepath = os.path.join(CACHE_DIR, filename)
    if os.path.exists(filepath):
        file_age = time.time() - os.path.getmtime(filepath)
        if file_age < max_age_seconds:
            try:
                with open(filepath, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
    return None

def save_to_cache(filename, data):
    """Saves data to a JSON cache file."""
    filepath = os.path.join(CACHE_DIR, filename)
    with open(filepath, 'w') as f:
        json.dump(data, f)

# --- WORLD CLOCK HANDLER ---
def get_world_clocks():
    """Returns formatted time strings for IST (Local) and CEST."""
    now_utc = datetime.now(ZoneInfo("UTC"))
    
    # Local Time (IST)
    time_ist = now_utc.astimezone(ZoneInfo("Asia/Kolkata"))
    
    # Central European Summer Time (CEST - typically maps to Europe/Paris or Europe/Berlin)
    time_cest = now_utc.astimezone(ZoneInfo("Europe/Paris")) 
    
    return {
        "local": time_ist.strftime("%I:%M %p"),
        "local_date": time_ist.strftime("%A, %B %d"),
        "cest": time_cest.strftime("%H:%M") # 24hr format is usually better for secondary alarms
    }

# --- WEATHER API (OpenWeatherMap) ---
def get_weather(api_key, city="Khordha,IN"):
    """Fetches current weather. Caches for 30 minutes."""
    if not api_key:
        return {"error": "No API Key configured"}

    cached = get_cached_data('weather.json', max_age_seconds=1800)
    if cached:
        return cached

    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
        print(f"DEBUG: OPWM {url=}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        print(f"DEBUG: OPWM {data=}")
        
        parsed_data = {
            "temp": round(data["main"]["temp"]),
            "feels_like": round(data["main"]["feels_like"]),
            "description": data["weather"][0]["description"].title(),
            "humidity": data["main"]["humidity"]
        }
        save_to_cache('weather.json', parsed_data)
        return parsed_data
        
    except Exception as e:
        print(f"[-] Weather API Error: {e}")
        return {"error": "API Sync Failed"}

# --- TODOIST API ---
def get_todoist_tasks(api_key, limit=5):
    """Fetches today's active tasks from Todoist. Caches for 15 minutes."""
    if not api_key:
        return [{"content": "No API Key configured", "priority": 1}]

    cached = get_cached_data('todoist.json', max_age_seconds=900)
    if cached:
        return cached

    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        # Fetch tasks due today or overdue
        url = "https://api.todoist.com/api/v1/tasks?filter=(today | overdue)"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        tasks = response.json()
        print(f"DEBUG: Todoist {tasks=}")
        
        
        parsed_tasks = []
        today = datetime.now().strftime("%Y-%m-%d")

        for t in tasks[:limit]:
            due = t.get("due")

            is_overdue = (
                due is not None and
                not due.get("is_recurring", False) and
                due.get("date") is not None and
                due["date"] < today
            )

            parsed_tasks.append({
                "content": t["content"],
                "priority": t["priority"],  # 4 highest
                "is_overdue": is_overdue
            })
            
        save_to_cache('todoist.json', parsed_tasks)
        return parsed_tasks
        
    except Exception as e:
        print(f"[-] Todoist API Error: {e}")
        return [{"content": "API Sync Failed", "priority": 1}]
    
# --- PICTURE OF THE DAY HANDLER ---
def download_image(url, save_path):
    """Streams an image from a URL to a local file."""
    try:
        response = requests.get(url, stream=True, timeout=15)
        response.raise_for_status()
        with open(save_path, 'wb') as out_file:
            shutil.copyfileobj(response.raw, out_file)
        return True
    except Exception as e:
        print(f"[-] Image Download Error: {e}")
        return False

def get_picture_of_the_day(source="nasa", api_key="", upload_dir="uploads"):
    """
    Fetches a daily image from the specified source, downloads it, 
    and processes it for the 3-color e-ink display.
    Caches the metadata and image for 12 hours.
    """
    cache_meta_file = f'potd_meta_{source}.json'
    raw_image_path = os.path.join(CACHE_DIR, f'potd_raw_{source}.jpg')
    
    # Check Cache (12 hours = 43200 seconds)
    cached = get_cached_data(cache_meta_file, max_age_seconds=43200)
    if cached and os.path.exists(raw_image_path):
        return cached

    img_url = None
    meta_data = {"source": source, "title": "Unknown", "credit": "Unknown"}

    try:
        # 1. NASA Astronomy Picture of the Day
        if source == "nasa":
            key = api_key if api_key else "DEMO_KEY"
            url = f"https://api.nasa.gov/planetary/apod?api_key={key}"
            res = requests.get(url, timeout=10).json()
            if "url" in res and res.get("media_type") == "image":
                img_url = res.get("hdurl", res["url"])
                meta_data["title"] = res.get("title", "NASA APOD")
                meta_data["credit"] = res.get("copyright", "NASA")

        # 2. Unsplash Random Landscape
        elif source == "unsplash":
            if not api_key:
                return {"error": "Unsplash requires an API Key"}
            url = f"https://api.unsplash.com/photos/random?orientation=landscape&query=nature&client_id={api_key}"
            res = requests.get(url, timeout=10).json()
            img_url = res["urls"]["regular"]
            meta_data["title"] = res.get("description", "Unsplash Photo") or "Unsplash Photo"
            meta_data["credit"] = res["user"]["name"]

        # 3. Reddit (e.g., /r/EarthPorn) - No API Key needed!
        elif source == "reddit":
            url = "https://www.reddit.com/r/EarthPorn/top.json?limit=5&t=day"
            headers = {"User-Agent": "InkyDashboard/1.0 (RaspberryPi)"} # Reddit requires a custom User-Agent
            res = requests.get(url, headers=headers, timeout=10).json()
            
            # Find the first post that is actually a direct image link
            for post in res["data"]["children"]:
                post_url = post["data"]["url"]
                if post_url.endswith(('.jpg', '.jpeg', '.png')):
                    img_url = post_url
                    meta_data["title"] = post["data"]["title"]
                    meta_data["credit"] = f"u/{post['data']['author']}"
                    break

        # Download and Process
        if img_url and download_image(img_url, raw_image_path):
            print(f"[*] Successfully downloaded {source} POTD. Processing palette...")
            # This slices the raw image into the Black and Red BMP layers for Page 3!
            process_upload(raw_image_path, upload_dir)
            save_to_cache(cache_meta_file, meta_data)
            return meta_data
        else:
            return {"error": "Failed to find or download a valid image."}

    except Exception as e:
        print(f"[-] POTD API Error ({source}): {e}")
        return {"error": f"API Request Failed: {str(e)}"}
    
# --- CALENDAR (iCal) HANDLER ---
def get_calendar_events(ical_url, limit=6):
    """
    Fetches an .ics calendar URL, parses recurring events, 
    and returns a sorted list of today's upcoming meetings.
    Caches for 30 minutes.
    """
    if not ical_url or not icalendar:
        return [{"title": "No Calendar URL or missing 'icalendar' lib", "time": ""}]

    cache_file = 'calendar_events.json'
    cached = get_cached_data(cache_file, max_age_seconds=1800)
    if cached:
        return cached

    raw_ical_path = os.path.join(CACHE_DIR, 'calendar.ics')

    try:
        # Download the .ics file 
        # (Using urllib with a custom header because some Google/Apple calendars block basic python requests)
        req = urllib.request.Request(ical_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response, open(raw_ical_path, 'wb') as out_file:
            out_file.write(response.read())

        # Parse the calendar
        with open(raw_ical_path, 'r') as f:
            cal = icalendar.Calendar.from_ical(f.read())

        # Extract events happening TODAY (handles recurring RRULEs perfectly)
        today = date.today()
        events_today = recurring_ical_events.of(cal).at(today)
        
        parsed_events = []
        for event in events_today:
            # Extract start time
            start_dt = event["DTSTART"].dt
            
            # Handle full-day events (they are parsed as 'date' objects instead of 'datetime')
            if isinstance(start_dt, date) and not isinstance(start_dt, datetime):
                time_str = "All Day"
            else:
                # Convert to local time (IST) and format
                local_dt = start_dt.astimezone(ZoneInfo("Asia/Kolkata"))
                time_str = local_dt.strftime("%I:%M %p")

            # Clean up the event summary/title
            title = str(event.get("SUMMARY", "Busy"))
            
            parsed_events.append({
                "title": title,
                "time": time_str,
                "timestamp": start_dt.timestamp() if isinstance(start_dt, datetime) else 0
            })

        # Sort chronologically by time
        parsed_events.sort(key=lambda x: x.get("timestamp", 0))
        
        # Remove the timestamp field before returning/caching and limit the results
        final_list = [{"title": e["title"], "time": e["time"]} for e in parsed_events[:limit]]
        
        if not final_list:
             final_list = [{"title": "No events scheduled for today!", "time": ""}]
             
        save_to_cache(cache_file, final_list)
        return final_list

    except Exception as e:
        print(f"[-] Calendar API Error: {e}")
        return [{"title": "Failed to sync calendar", "time": ""}]