
# Inky

Inky is a highly modular, smart e-ink dashboard powered by a Raspberry Pi and a Waveshare 7.5" (V2) Black/White/Red screen.

Rebuilt from the ground up for maximum flexibility, it features a 3-page layout with 3 distinct modes per page. Everything is managed through a sleek local web interface and controlled physically via GPIO hardware interrupts. It also includes an API endpoint to push custom graphs to the screen instantly.

## Features & Modes

**Page 1: The Daily Hub (Clock, Environment & APIs)**

* **Mode 1 (Dashboard):** World clocks, and OpenWeather forecast local with DHT11 temperature and humidity.
* **Mode 2 (Qoutes):** A dynamic quote generator (via uploaded CSVs).
* **Mode 3 (API Push):** A passive listener mode. Push any custom B&W image (like a network graph or custom dashboard) via a REST API. It uses `ImageChops` to calculate the exact pixel difference and executes a blazing-fast targeted partial update.

**Page 2: Productivity (Tasks & Scheduling)**

* **Mode 1 (Tasks):** Pulls active tasks from the Todoist API, highlighting high-priority items in red ink.
* **Mode 2 (Agenda):** Parses any `.ics` iCal link (Google Calendar, Apple, etc.) to show today's upcoming events.
* **Mode 3 (Scratchpad):** Renders custom Markdown notes set from the Web UI.

**Page 3: The Art Gallery**

* **Mode 1 (Static):** Displays a single favorite photo.
* **Mode 2 (Slideshow):** Cycles through a local directory of pre-processed e-ink images at a custom interval.
* **Mode 3 (POTD):** Automatically fetches, dithers, and displays the Picture of the Day from NASA, Unsplash, or Reddit.

## Hardware Requirements

* Raspberry Pi (Zero W, 3, or 4 recommended)
* Waveshare 7.5" E-Ink Display HAT (V2 - 800x480 Resolution, B/W/R)
* DHT11 (or DHT22) Temperature/Humidity Sensor (Connected to GPIO 5)
* 4x Push Buttons:
* **GPIO 6** (Page 1)
* **GPIO 13** (Page 2)
* **GPIO 19** (Page 3)
* **GPIO 26** (Manual Refresh / Sync)



---

## 🛠 Setup & Installation

### 1. Enable Hardware SPI

The e-ink display requires the hardware SPI interface to be enabled.

1. Run `sudo raspi-config` in your terminal.
2. Navigate to **Interface Options** > **SPI**.
3. Select **<Yes>** to enable the SPI interface.
4. Reboot your Pi: `sudo reboot`

### 2. Install System Dependencies

Modern Raspberry Pi OS (Bookworm and later) requires specific C-libraries and headers to compile the GPIO and sensor bindings. Run:

```bash
sudo apt update
sudo apt install -y libgpiod2 swig liblgpio-dev python3-dev avahi-daemon
sudo usermod -a -G gpio $USER
```

### 3. Install `uv`

This project uses `uv` for blazing-fast Python package management and virtual environment isolation.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

*(You may need to restart your terminal or source your profile after installation).*

### 4. Clone the Repository

```bash
git clone https://github.com/Sarin-jacob/Inky.git
cd Inky
```

### 5. Install Python Dependencies

Use `uv` to automatically create a virtual environment and sync all required packages.

```bash
uv sync
```

### 6. Setup Systemd Serice (optional)

```bash
chmod +x install.sh && ./install.sh
```
- To check the status:  `sudo systemctl status Inky`
- To view live logs:    `sudo journalctl -u Inky -f`
- To stop the service:  `sudo systemctl stop Inky`

---

## Running the Application & Usage

Because the application requires direct hardware access to the SPI bus and precise microsecond timing for the DHT sensor, it must be run with `sudo` privileges [when seet as service]. Run the main hardware loop (which automatically launches the web server):

If setup as Service:
```bash
sudo systemctl start Inky
```
else:
```bash
sudo uv run main.py
```

### Web Interface & Configuration

* Open a browser on your network and navigate to `http://inky.local` (or the Pi's IP address).
* Use the dashboard to input your API keys (Todoist, OpenWeather, etc.), upload photos, manage your slideshow interval, and set up Wi-Fi.
* Inky have another trick up its sleeve, If Inky dosent find or cannot connect to know wireless network it would create a fallback Ap with the following Credentials
    - SSID : `Inky_Hotspot`
    - Passd: `SecurePass123`

### Hardware Button Navigation

* **Short Press (Btn 1, 2, 3):** Jump directly to that Page.
* **Long Press (Hold for 3 seconds):** Cycle through the 3 Modes for the current page.
* **Short Press (Btn 4):** Force a full screen refresh to clear e-ink ghosting.
* **System Reboot:** Hold Button 1 + Button 3 together for 5 seconds to trigger a safe `sudo reboot`.

### The API Push Endpoint (Page 1, Mode 3)

You can instantly update the screen from another machine on your network by sending a B&W image to the API.

```bash
curl -X POST -F "image=@my_custom_graph.png" http://inky.local/api/push_image
```
#### Example:
Download [system_usage.py](https://github.com/Sarin-jacob/Inky/blob/main/plugins/system_usage.py) and run the following after setting Inky to `Api push Mode`.

```bash
uv run system_usage.py
```

---

## Troubleshooting, Quirks & Workarounds

Working with 3-Color E-Ink displays and Raspberry Pi GPIO requires navigating a few hardware quirks. Here is how the codebase handles them (and what to look out for if you modify it):

* **Quirk: Partial Updates Crash or Garble the Screen**
* *The Rule:* Due to how the SPI memory buffer processes pixels, any partial update bounding box must have an **X-coordinate and Width that is a multiple of 8** (e.g., 1 byte = 8 pixels).
* *Workaround:* If you write custom `push_partial_update` logic, ensure your `(X1, Y1, X2, Y2)` box adheres to this. For example, `X=536` works, but `X=540` will scramble the image.


* **Quirk: The Red Layer Gets "Muddy" or Ghosts Heavily**
* *The Rule:* The red ink particles move slower than the black/white particles. Rapid partial updates that attempt to draw red will leave permanent pink ghosting until a full refresh clears the screen.
* *Workaround:* The `push_partial_update()` function in this codebase strictly ignores the red image buffer and only pushes B&W data. Any feature relying on fast minute-ticks (like the clock) is strictly black and white.


* **Quirk: Screen "Burn-in" / Ghosting Over Time**
* *The Rule:* E-ink screens retain slight impressions of previous images if not properly flushed.
* *Workaround:* The `hardware_loop` maintains a timer and automatically dispatches a deep, full-screen flush (which flashes the screen a few times) every 1 hour, or whenever you switch pages/modes.


* **Quirk: DHT11 Sensor "Fails to Read"**
* *The Rule:* The DHT11 requires strict microsecond timing. If the Pi's CPU is busy (like rendering an image or handling a web request), it might miss the sensor pulse.
* *Workaround:* The `get_sensor_string()` utility includes a silent retry loop that attempts to read the sensor 3 times with a 1-second delay before displaying a "Sensor Error" on the screen.



---

*This project uses assets from [https://github.com/KalebClark/Inky](https://github.com/KalebClark/Inky) and originated from the source code of said project.*
