#!/usr/bin/env python3
import time
import board
import adafruit_dht
import RPi.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont

# Import your local driver
from driver import epd7in5b

# Hardware Pins
DHT_PIN = board.D5
BUTTONS = [6, 13, 19, 26]

def test_dht():
    print("\n--- 1. Testing DHT Sensor ---")
    dht_device = adafruit_dht.DHT11(DHT_PIN) # Change to DHT11 if using a DHT11
    
    # DHT sensors often fail the first read, so we try a few times
    for attempt in range(4):
        try:
            temp = dht_device.temperature
            hum = dht_device.humidity
            print(f"[SUCCESS] Temperature: {temp:.1f}°C, Humidity: {hum:.1f}%")
            return
        except RuntimeError as error:
            print(f"Read {attempt + 1} failed (normal behavior): {error.args[0]}")
            time.sleep(2.0)
        except Exception as error:
            dht_device.exit()
            print(f"[FAILED] Fatal DHT Error: {error}")
            return
            
    print("[FAILED] Could not get a reading from the DHT sensor after multiple attempts.")

def test_display():
    print("\n--- 2. Testing E-Ink Display ---")
    try:
        print("Initializing EPD...")
        epd = epd7in5b.EPD()
        epd.init()

        print("Creating test image...")
        # 255 is White for this driver
        image = Image.new('L', (epd.width, epd.height), 255) 
        draw = ImageDraw.Draw(image)

        # Try to load your Roboto font, fallback to default if missing
        try:
            font = ImageFont.truetype("fonts/roboto/Roboto-Black.ttf", 48)
        except Exception:
            print("Could not load Roboto font, using default.")
            font = ImageFont.load_default()

        # Write text in Black (0) and Red (128)
        draw.text((50, 50), "HARDWARE TEST", font=font, fill=0)
        draw.text((50, 150), "E-INK IS WORKING!", font=font, fill=128)

        print("Pushing image to display (this will take a few seconds)...")
        epd.display_frame(epd.get_frame_buffer(image))
        epd.sleep()
        print("[SUCCESS] Display test complete. Check the screen!")
        
    except Exception as e:
        print(f"[FAILED] Display test encountered an error: {e}")

def button_callback(channel):
    print(f"\n[SUCCESS] --> BUTTON PRESSED ON GPIO {channel}!")

def test_buttons():
    print("\n--- 3. Testing GPIO Buttons ---")
    try:
        # Set up GPIO mode if not already set by driver
        GPIO.setmode(GPIO.BCM)
    except Exception:
        pass

    for btn in BUTTONS:
        try:
            GPIO.setup(btn, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(btn, GPIO.FALLING, callback=button_callback, bouncetime=300)
            print(f"Listening on GPIO {btn}...")
        except Exception as e:
            print(f"[FAILED] Could not setup GPIO {btn}: {e}")

    print("\nTest is now running. Press your physical buttons to see output.")
    print("Press CTRL+C to exit the test.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nCleaning up GPIO and exiting...")
        GPIO.cleanup()

if __name__ == '__main__':
    print("Starting InfoWindow Hardware Diagnostics...\n")
    test_dht()
    test_display()
    test_buttons()
