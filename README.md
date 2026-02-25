# InfoWindow 

InfoWindow is a smart, hardware-responsive e-ink display powered by a Raspberry Pi and a Waveshare 7.5" (V2) screen. It features a desk calendar/clock, a task manager (Todoist/Google Calendar), and a custom photo viewer. Everything is managed through a lightweight local web interface and controlled physically via GPIO buttons.

## Features
* **Page 1: Clock & Environment** - Displays the current time, date, and local room temperature/humidity via a DHT11 sensor. Updates every 5 minutes.
* **Page 2: Task View** - Integrates with Todoist or Google Calendar to display your upcoming tasks.
* **Page 3: Photo Viewer** - Displays a custom image. Images uploaded via the web interface are automatically dithered and converted to a 3-color (Red/Black/White) palette optimized for the e-ink display.
* **Web Control Panel** - A local Flask web server (`http://<pi-ip>:5000`) to switch pages, change task sources, and upload photos.
* **Physical Buttons** - Instant page-switching using hardware interrupts.

## Hardware Requirements
* Raspberry Pi (Zero W, 3, or 4 recommended)
* Waveshare 7.5" E-Ink Display HAT (V2 - 800x480 Resolution)
* DHT11 (or DHT22) Temperature and Humidity Sensor (Connected to GPIO 5)
* 3x Push Buttons (Connected to GPIO 6, 13, and 19)

---

## 🛠 Setup & Installation

### 1. Enable Hardware SPI
The e-ink display requires the hardware SPI interface to be enabled on your Raspberry Pi.
1. Run `sudo raspi-config` in your terminal.
2. Navigate to **Interface Options** > **SPI**.
3. Select **<Yes>** to enable the SPI interface.
4. Reboot your Pi: `sudo reboot`

### 2. Install System Dependencies
Modern Raspberry Pi OS (Bookworm and later) requires specific C-libraries and headers to compile the GPIO and sensor bindings. Run the following command:
```bash
sudo apt update
sudo apt install -y libgpiod2 swig liblgpio-dev python3-dev avahi-daemon
```

### 3. Install `uv`

This project uses `uv` for blazing-fast Python package management and virtual environment isolation. If you don't have it installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

*(You may need to restart your terminal or source your profile after installation).*

### 4. Clone the Repository

```bash
git clone https://github.com/Sarin-jacob/InfoWindow.git
cd InfoWindow
git switch shrink #Working on remaking the code
```

### 5. Install Python Dependencies

Use `uv` to automatically create a virtual environment and sync all required packages (including `Flask`, `Pillow`, `rpi-lgpio`, and `adafruit-circuitpython-dht`).

```bash
uv sync
```

---

## Running the Application

Because the application requires direct hardware access to the SPI bus and precise microsecond timing for the DHT sensor, it must be run with `sudo` privileges using the virtual environment's Python binary.

From the `InfoWindow` directory, run:

```bash
uv run app.py
```

### Usage

* **Web Interface:** Open a browser on any device connected to the same network and navigate to `http://<raspberry-pi-ip>:5000`.
* **Hardware Buttons:** Press the physical buttons to instantly wake the screen and change the active page.

---

This project is usign assets from https://github.com/KalebClark/InfoWindow and started from the source code of said project.