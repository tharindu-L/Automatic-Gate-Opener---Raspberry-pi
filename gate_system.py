import os
import re
import time
import threading
import numpy as np
import cv2
import pytesseract
from flask import Flask, request, redirect
from picamera2 import Picamera2
from gpiozero import OutputDevice
from PIL import ImageFont

PLATES_FILE = "/home/pi/plates.txt"
RELAY_PIN = 17
GATE_OPEN_SECONDS = 5

app = Flask(__name__)
relay = OutputDevice(RELAY_PIN, active_high=False, initial_value=False)

display = None
try:
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    from luma.core.render import canvas
    serial_interface = i2c(port=1, address=0x3C)
    display = ssd1306(serial_interface)
    print("OLED display found and ready.")
except Exception as e:
    print("No OLED display connected. Continuing without display.")

picam2 = Picamera2()
camera_config = picam2.create_still_configuration(main={"size": (640, 480), "format": "RGB888"})
picam2.configure(camera_config)
picam2.start()
time.sleep(2)

display_lock = threading.Lock()

def show_display(line1="", line2="", line3="", line4=""):
    if display is None:
        print(f"Display: {line1} | {line2} | {line3} | {line4}")
        return
    with display_lock:
        from luma.core.render import canvas
        with canvas(display) as draw:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
                font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
            except:
                font = ImageFont.load_default()
                font_small = font
            if line1:
                draw.text((0, 0),  line1, fill="white", font=font)
            if line2:
                draw.text((0, 14), line2, fill="white", font=font_small)
            if line3:
                draw.text((0, 27), line3, fill="white", font=font_small)
            if line4:
                draw.text((0, 40), line4, fill="white", font=font_small)

def ensure_plates_file():
    if not os.path.exists(PLATES_FILE):
        open(PLATES_FILE, 'w').close()

def read_plates():
    ensure_plates_file()
    with open(PLATES_FILE, 'r') as f:
        plates = [line.strip() for line in f.readlines() if line.strip()]
    return plates

def add_plate(plate):
    plate = plate.strip().upper()
    if plate:
        plates = read_plates()
        if plate not in plates:
            with open(PLATES_FILE, 'a') as f:
                f.write(plate + "\n")

def remove_plate(plate):
    plate = plate.strip().upper()
    plates = read_plates()
    updated = [p for p in plates if p != plate]
    with open(PLATES_FILE, 'w') as f:
        f.write("\n".join(updated) + "\n" if updated else "")

def is_plate_allowed(plate):
    plate = plate.strip().upper()
    return plate in read_plates()

def capture_image():
    frame = picam2.capture_array()
    return frame

def read_plate_from_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.equalizeHist(gray)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    custom_config = r'--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'
    text = pytesseract.image_to_string(thresh, config=custom_config)
    cleaned = re.sub(r'[^A-Z0-9\-]', '', text.upper())
    has_letter = any(c.isalpha() for c in cleaned)
    has_number = any(c.isdigit() for c in cleaned)
    if 4 <= len(cleaned) <= 10 and has_letter and has_number:
        return cleaned
    return ""

def open_gate():
    relay.on()
    show_display("Gate System", "Status: ALLOWED", "Gate: OPENING", "")
    time.sleep(GATE_OPEN_SECONDS)
    relay.off()
    show_display("Gate System", "Ready", "Waiting for", "vehicle...")

@app.route('/')
def handle_root():
    plates = read_plates()
    html = "<!DOCTYPE html><html><head>"
    html += "<meta charset='utf-8'>"
    html += "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    html += "<title>Gate Control</title>"
    html += "<style>"
    html += "body{font-family:Arial,sans-serif;max-width:480px;margin:30px auto;padding:0 16px}"
    html += "h2{color:#333}"
    html += "div.plate{display:flex;align-items:center;justify-content:space-between;padding:8px;margin:4px 0;background:#f4f4f4;border-radius:6px}"
    html += "input[type=text]{padding:8px;width:200px;border:1px solid #ccc;border-radius:4px}"
    html += "button,input[type=submit]{padding:8px 14px;background:#d9534f;color:#fff;border:none;border-radius:4px;cursor:pointer}"
    html += ".add-btn{background:#5cb85c!important}"
    html += ".capture-btn{background:#337ab7;color:#fff;padding:10px 18px;border:none;border-radius:4px;cursor:pointer;font-size:15px;margin-top:12px;width:100%}"
    html += "</style></head><body>"
    html += "<h2>&#128663; Gate Plate Manager</h2>"
    html += "<form action='/capture' method='GET'>"
    html += "<button class='capture-btn' type='submit'>&#128247; Capture &amp; Check Plate</button>"
    html += "</form><hr>"
    html += "<h3>Allowed Plates</h3>"
    if plates:
        for plate in plates:
            html += "<div class='plate'><span>" + plate + "</span>"
            html += "<form action='/remove' method='POST'>"
            html += "<input type='hidden' name='plate' value='" + plate + "'>"
            html += "<input type='submit' value='Remove'>"
            html += "</form></div>"
    else:
        html += "<p style='color:#888'>No plates added yet.</p>"
    html += "<hr><h3>Add Plate</h3>"
    html += "<form action='/add' method='POST'>"
    html += "<input type='text' name='plate' placeholder='e.g. CAA-1234' maxlength='12'> "
    html += "<input type='submit' class='add-btn' value='Add'>"
    html += "</form></body></html>"
    return html

@app.route('/add', methods=['POST'])
def handle_add():
    plate = request.form.get('plate', '')
    add_plate(plate)
    return redirect('/')

@app.route('/remove', methods=['POST'])
def handle_remove():
    plate = request.form.get('plate', '')
    remove_plate(plate)
    return redirect('/')

@app.route('/capture')
def handle_capture():
    show_display("Gate System", "Capturing...", "", "")
    image = capture_image()
    show_display("Gate System", "Reading plate...", "", "")
    detected_plate = read_plate_from_image(image)
    print(f"Detected plate: '{detected_plate}'")

    if not detected_plate:
        show_display("Gate System", "No plate found", "Try again", "")
        html = "<!DOCTYPE html><html><body style='font-family:Arial;text-align:center;padding:40px'>"
        html += "<h2>&#128247; Capture Result</h2>"
        html += "<div style='font-size:18px;padding:20px;background:#f0ad4e;color:#fff;border-radius:8px;margin:20px 0'>"
        html += "No plate detected. Please try again."
        html += "</div>"
        html += "<br><a href='/'>&#8592; Back</a>"
        html += "</body></html>"
        return html

    if is_plate_allowed(detected_plate):
        threading.Thread(target=open_gate).start()
        color = "#5cb85c"
        message = "Plate <strong>" + detected_plate + "</strong> is ALLOWED. Gate opening!"
    else:
        show_display("Gate System", "Plate: " + detected_plate, "Status: DENIED", "Gate: CLOSED")
        color = "#d9534f"
        message = "Plate <strong>" + detected_plate + "</strong> is NOT allowed. Gate stays closed."

    html = "<!DOCTYPE html><html><body style='font-family:Arial;text-align:center;padding:40px'>"
    html += "<h2>&#128247; Capture Result</h2>"
    html += "<div style='font-size:18px;padding:20px;background:" + color + ";color:#fff;border-radius:8px;margin:20px 0'>"
    html += message
    html += "</div>"
    html += "<br><a href='/'>&#8592; Back to Plate Manager</a>"
    html += "</body></html>"
    return html

if __name__ == '__main__':
    ensure_plates_file()
    show_display("Gate System", "Starting...", "Please wait", "")
    time.sleep(1)
    show_display("Gate System", "Ready", "192.168.4.1", "Waiting...")
    print("Gate system started. Open http://192.168.4.1 in your browser.")
    app.run(host='0.0.0.0', port=80, debug=False)
