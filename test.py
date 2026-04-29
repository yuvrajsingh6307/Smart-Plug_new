from machine import Pin, ADC, I2C
import network
import time
from umqtt.simple import MQTTClient
import math
from i2c_lcd import I2cLcd

# ==============================
# LCD Setup
# ==============================
i2c = I2C(0, scl=Pin(26), sda=Pin(27), freq=400000)
lcd = I2cLcd(i2c, 0x27, 2, 16)

lcd.clear()
lcd.putstr("Hello")
lcd.move_to(0, 1)
lcd.putstr("Smart Plug")
time.sleep(2)
lcd.clear()

# ==============================
# WiFi Config
# ==============================
SSID     = "iQOO Neo9 Pro"
PASSWORD = "12345678"

# ==============================
# Adafruit IO Config
# ==============================
AIO_USERNAME = "yuvrajsingh01"
AIO_KEY      = "aio_loIa11XRcEMmpRm2lDmY4RIQeLoN"

RELAY_FEED   = "relay"
TIMER_FEED   = "timer"
RESET_FEED   = "reset"

VOLTAGE_FEED = "voltage"
CURRENT_FEED = "current"
POWER_FEED   = "power"
ENERGY_FEED  = "energy"
STATUS_FEED  = "status"
ALERT_FEED   = "alerts"
COST_FEED    = "cost"

# ==============================
# Relay
# ==============================
relay        = Pin(18, Pin.OUT)
relay.value(0)           # Start OFF for safety
relay_state  = "OFF"
last_status  = ""

# ==============================
# Timer
# ==============================
timer_value  = 0
timer_start  = 0
timer_active = False

# ==============================
# Safety
# ==============================
MAX_CURRENT      = 2.0    # Amps
MAX_POWER        = 300.0  # Watts
safety_triggered = False
safety_reason    = ""

# ==============================
# ADC Setup
# ==============================
adc_v = ADC(Pin(35))
adc_v.atten(ADC.ATTN_11DB)
adc_v.width(ADC.WIDTH_12BIT)

adc_i = ADC(Pin(34))
adc_i.atten(ADC.ATTN_11DB)
adc_i.width(ADC.WIDTH_12BIT)

ADC_MAX = 4095
VREF    = 3.3
SAMPLES = 1000   # For voltage RMS

# ==============================
# ACS712 Current Sensor Config
# Mirrors Arduino: ACS712 ACS(34, 3.3, 4095, 125)
#
# ACS_SENSITIVITY  = mV per Amp
#   5A  module → 185 mV/A
#   20A module → 100 mV/A
#   30A module → 66  mV/A
# ==============================
ACS_SENSITIVITY    = 110      # mV/A — change for 20A=100, 30A=66
CALIBRATION_OFFSET = 75        # Set to 0 first, tune after testing
NOISE_FLOOR_MA     = 5.0      # mA  — mirrors Arduino: if (mA <= 5) mA = 0
AC_SAMPLES         = 100      # mirrors Arduino: for (int i = 0; i < 100; i++)

# ==============================
# Voltage Config
# ==============================
CALIBRATION_FACTOR = 466.1
NOISE_THRESHOLD_V  = 0.03
alpha_v            = 0.6
last_voltage       = 0.0

# ==============================
# Cost
# ==============================
COST_PER_UNIT = 8.0     # Rs per kWh

# ==============================
# State
# ==============================
energy           = 0.0
last_alert       = ""
current_midpoint = 2048   # Will be calibrated at boot

# ==============================
# Helper: ADC Midpoint
# ==============================
def get_midpoint(adc, samples=500):
    total = 0
    for _ in range(samples):
        total += adc.read()
        time.sleep_us(200)
    return total / samples

# ==============================
# WiFi Connect
# ==============================
def connect_wifi():
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)
    wifi.connect(SSID, PASSWORD)
    lcd.clear()
    lcd.putstr("Connecting WiFi")
    attempts = 0
    while not wifi.isconnected():
        time.sleep(1)
        attempts += 1
        if attempts > 20:
            lcd.clear()
            lcd.putstr("WiFi Failed!")
            time.sleep(2)
            return
    lcd.clear()
    lcd.putstr("WiFi OK")
    print("WiFi:", wifi.ifconfig())
    time.sleep(1)

connect_wifi()

# ==============================
# Calibrate Current Sensor at Boot
# Relay must be OFF (no load) for accurate zero
# ==============================
lcd.clear()
lcd.putstr("Calibrating...")
lcd.move_to(0, 1)
lcd.putstr("No load please")
time.sleep(1)

current_midpoint = get_midpoint(adc_i, samples=500)
print("Midpoint:", current_midpoint)

lcd.clear()
lcd.putstr("Cal OK")
lcd.move_to(0, 1)
lcd.putstr("Mid:{:.0f}".format(current_midpoint))
time.sleep(1)
lcd.clear()

# ==============================
# MQTT Topics
# ==============================
MQTT_BROKER = "io.adafruit.com"
CLIENT_ID   = "esp32_energy"

def topic(feed):
    return b"%s/feeds/%s" % (AIO_USERNAME.encode(), feed.encode())

relay_topic   = topic(RELAY_FEED)
timer_topic   = topic(TIMER_FEED)
reset_topic   = topic(RESET_FEED)
voltage_topic = topic(VOLTAGE_FEED)
current_topic = topic(CURRENT_FEED)
power_topic   = topic(POWER_FEED)
energy_topic  = topic(ENERGY_FEED)
status_topic  = topic(STATUS_FEED)
alert_topic   = topic(ALERT_FEED)
cost_topic    = topic(COST_FEED)

# ==============================
# MQTT Callback
# ==============================
def on_message(t, msg):
    global relay_state, timer_value, timer_start, timer_active
    global safety_triggered, safety_reason, current_midpoint

    if t == relay_topic:
        if msg in [b'1', b'ON', b'on', b'true']:
            if not safety_triggered:
                relay.value(1)
                relay_state = "ON"
                print("Relay ON")
            else:
                print("Blocked — safety:", safety_reason)

        elif msg in [b'0', b'OFF', b'off', b'false']:
            relay.value(0)
            relay_state = "OFF"
            print("Relay OFF — recalibrating...")
            current_midpoint = get_midpoint(adc_i, samples=300)
            print("New midpoint:", current_midpoint)

    elif t == timer_topic:
        try:
            timer_value = int(msg)
            if timer_value == 0:
                relay.value(0)
                relay_state  = "OFF"
                timer_active = False
                print("Timer cancelled")
            elif timer_value > 0:
                timer_start  = time.time()
                timer_active = True
                print("Timer:", timer_value, "s")
        except:
            pass

    elif t == reset_topic:
        if msg == b'1':
            safety_triggered = False
            safety_reason    = ""
            print("Safety reset")

# ==============================
# MQTT Connect
# ==============================
client = MQTTClient(CLIENT_ID, MQTT_BROKER,
                    user=AIO_USERNAME, password=AIO_KEY)
client.set_callback(on_message)
client.connect()
client.subscribe(relay_topic)
client.subscribe(timer_topic)
client.subscribe(reset_topic)
print("MQTT connected")

# ==============================
# Read Voltage RMS
# ==============================
def read_voltage():
    global last_voltage

    midpoint = get_midpoint(adc_v, samples=200)
    sum_sq   = 0.0

    for _ in range(SAMPLES):
        raw      = adc_v.read()
        centered = raw - midpoint
        v        = centered * (VREF / ADC_MAX)
        sum_sq  += v * v
        time.sleep_us(100)

    vrms = math.sqrt(sum_sq / SAMPLES)

    if vrms < NOISE_THRESHOLD_V:
        last_voltage = 0.0
        return 0.0

    voltage      = vrms * CALIBRATION_FACTOR
    voltage      = alpha_v * voltage + (1 - alpha_v) * last_voltage
    last_voltage = voltage
    return round(voltage, 1)

# ==============================
# mA_AC() — Mimics ACS712 library
#
# Arduino library internally:
#   1. Samples ADC over ~1 AC cycle (20ms for 50Hz)
#   2. Subtracts midpoint (zero crossing)
#   3. Computes RMS voltage
#   4. Divides by sensitivity → Amps → mA
# ==============================
def mA_AC():
    sum_sq        = 0.0
    cycle_samples = 200      # 200 x 100us = 20ms = one 50Hz cycle

    for _ in range(cycle_samples):
        raw      = adc_i.read()
        centered = raw - current_midpoint
        v        = centered * (VREF / ADC_MAX)
        sum_sq  += v * v
        time.sleep_us(100)

    vrms = math.sqrt(sum_sq / cycle_samples)

    # Sensitivity in V/A = ACS_SENSITIVITY / 1000
    mA = (vrms / (ACS_SENSITIVITY / 1000.0)) * 1000.0
    return mA

# ==============================
# read_current() — Exact Arduino logic:
#
#   float average = 0;
#   for (int i = 0; i < 100; i++) {
#       average += ACS.mA_AC();
#   }
#   float mA = abs(average / 100.0) - calibration_factor;
#   if (mA <= 5) mA = 0;
# ==============================
def read_current():
    global current_midpoint

    # Step 1: Get stable midpoint ONCE before sampling
    # (not inside the loop — this was causing signal distortion)
    midpoint = current_midpoint   # Use boot-calibrated value

    # Step 2: Collect raw samples across multiple AC cycles
    # 50Hz = 20ms per cycle → 1000 samples at 100us = 10 full cycles
    # More cycles = more accurate RMS
    num_samples = 1000
    sum_sq = 0.0

    for _ in range(num_samples):
        raw      = adc_i.read()
        centered = raw - midpoint
        v        = centered * (VREF / ADC_MAX)
        sum_sq  += v * v
        time.sleep_us(100)      # 100us × 1000 = 100ms = 5 full 50Hz cycles

    # Step 3: Compute RMS voltage
    vrms = math.sqrt(sum_sq / num_samples)

    # Step 4: Convert to mA using ACS712 formula
    # I(A) = Vrms / sensitivity(V/A)
    mA = (vrms / (ACS_SENSITIVITY / 1000.0)) * 1000.0

    # Step 5: Subtract noise offset (should be small, 0-30mA)
    mA = mA - CALIBRATION_OFFSET

    # Step 6: Zero noise floor
    if mA <= NOISE_FLOOR_MA:
        mA = 0.0

    mA = max(0.0, mA)   # Never go negative

    print("vrms: {:.4f}V  Current: {:.1f} mA".format(vrms, mA))
    return round(mA / 1000.0, 3)   # Return Amps
    # Return Amps for power calc

# ==============================
# Update LCD
# ==============================
def update_lcd(voltage, current_A, power, cost):
    current_mA = round(current_A * 1000, 0)
    lcd.clear()
    lcd.move_to(0, 0)
    lcd.putstr("V:{}V {}mA".format(voltage, int(current_mA)))
    lcd.move_to(0, 1)
    lcd.putstr("Rs:{} P:{}W".format(cost, power))

# ==============================
# Main Loop
# ==============================
last_send      = 0
SEND_INTERVAL  = 15
energy_counter = 0

while True:

    try:
        client.check_msg()
    except Exception as e:
        print("MQTT error:", e)
        try:
            client.connect()
            client.subscribe(relay_topic)
            client.subscribe(timer_topic)
            client.subscribe(reset_topic)
        except:
            pass

    # ---- Timer Check ----
    if timer_active:
        if time.time() - timer_start >= timer_value:
            relay.value(0)
            relay_state  = "OFF"
            timer_active = False
            print("Timer expired")

    # ---- Sensor + Publish ----
    if time.time() - last_send >= SEND_INTERVAL:

        voltage   = read_voltage()
        current_A = read_current()
        power     = round(voltage * current_A, 1)

        # Safety
        if not safety_triggered:
            if current_A > MAX_CURRENT:
                safety_triggered = True
                safety_reason    = "Over Current"
                print("SAFETY: Over Current")
            elif power > MAX_POWER:
                safety_triggered = True
                safety_reason    = "Over Power"
                print("SAFETY: Over Power")

        if safety_triggered:
            relay.value(0)
            relay_state = "OFF"

        # Energy & Cost
        energy = round(energy + (power * SEND_INTERVAL) / 3600000.0, 4)
        cost   = round(energy * COST_PER_UNIT, 2)

        # LCD
        update_lcd(voltage, current_A, power, cost)

        # Status
        actual_status = "OFF" if relay.value() == 0 else "ON"
        if actual_status != last_status:
            try:
                client.publish(status_topic, actual_status)
                last_status = actual_status
            except:
                pass

        # Alerts
        if safety_triggered:
            alert_msg = "ALERT: " + safety_reason
        elif current_A > MAX_CURRENT:
            alert_msg = "High Current"
        elif power > MAX_POWER:
            alert_msg = "High Power"
        elif voltage == 0:
            alert_msg = "No Supply"
        else:
            alert_msg = "Normal"

        if alert_msg != last_alert:
            try:
                client.publish(alert_topic, alert_msg)
                last_alert = alert_msg
            except:
                pass

        # MQTT Publish (staggered to avoid rate limits)
        try:
            client.publish(voltage_topic, str(voltage))
            client.publish(current_topic, str(round(current_A * 1000, 1)))  # in mA

            if energy_counter % 2 == 0:
                client.publish(power_topic, str(power))
            if energy_counter % 3 == 0:
                client.publish(cost_topic, str(cost))
            if energy_counter % 4 == 0:
                client.publish(energy_topic, str(energy))

            energy_counter += 1

        except Exception as e:
            print("Publish error:", e)

        last_send = time.time()

    time.sleep(0.1)