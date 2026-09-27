# WT901BLE on Mac and Windows

The photographed label appears to be **WT901BLECL5.0**. Confirm the model in
the manufacturer's app or purchase record before applying firmware/configuration
commands. This agent expects the WT901 BLE service `FFE5`, notification
characteristic `FFE4`, and 20-byte `55 61` acceleration/gyro/angle frames. It checks
the service before collecting data.

USB-C also carries sensor data on the tested unit; it is not limited to
charging. WitMotion documents USB-C data transfer for this model. Use a data
cable and a USB serial port as an alternative to Bluetooth.
[WitMotion model documentation](https://witmotion-sensor.com/products/bluetooth-5-0-accelerometer-inclinometer-wt901blecl-mpu9250-9-axis-imu-sensor)

## Install once on each computer

Use a native terminal on the computer whose Bluetooth adapter will connect to
the sensor. Do not run the Bluetooth agent inside Docker, a remote session on
another computer, or WSL. The web app and base station can run elsewhere.

Prerequisites: Python **3.10+** (3.12 is a suitable choice), internet access for
initial dependency installation, and a working Bluetooth Low Energy adapter.
The pinned Bleak 3.0.2 transport documents **macOS 10.15+** and **Windows 11
build 22000+**. Older Windows versions are not supported by this pinned setup;
do not silently downgrade the BLE dependency.
[Bleak supported platforms](https://bleak.readthedocs.io/en/latest/)

From the repository root on Mac:

```sh
python3 scripts/hardware/wt901_desktop.py setup
python3 scripts/hardware/wt901_desktop.py run --scan --scan-seconds 10
```

If `python3 --version` shows 3.9 or earlier, install a newer Python and use its
executable (for example `python3.12`) for both commands. Apple's system Python
may be too old. The launcher creates `venv/wt901` within this checkout and does
not install packages into the system Python.

In Windows PowerShell, from a checkout of this repository:

```powershell
py -3.12 scripts/hardware/wt901_desktop.py setup
py -3.12 scripts/hardware/wt901_desktop.py run --scan --scan-seconds 10
```

Use the Python version you actually installed if it differs from 3.12. No
PowerShell execution-policy changes or virtual-environment activation are needed.

Power on the sensor and close other apps/connections using it before scanning.
Connect from **one computer at a time**. To move it between computers, stop the
first agent with Ctrl+C, then scan from the second computer. On Mac, allow
Bluetooth for the terminal under **System Settings → Privacy & Security →
Bluetooth**. Bleak returns a local UUID on Mac and an address on Windows: scan
on each computer, and copy that computer's identifier exactly. The printed
serial number on the case is not the connection identifier.
[Bleak macOS permissions](https://bleak.readthedocs.io/en/latest/backends/macos.html)
[Bleak device identifiers](https://bleak.readthedocs.io/en/latest/api/client.html)

## USB connection instead of Bluetooth

After setup, plug in a USB data cable and list the available serial ports:

```sh
python3 scripts/hardware/wt901_desktop.py run --list-ports
```

Copy the sensor port from that list; macOS normally shows `/dev/cu.*`, Windows
shows `COM` followed by a number. For example:

```sh
python3 scripts/hardware/wt901_desktop.py run --serial-port /dev/cu.usbserial-EXAMPLE --baud 115200 --node-id rack_1 --hz 50 --capture-path trial.jsonl
```

On Windows, replace `python3` with `py -3.12` and the serial port with the actual
port, such as `COM3`. This unit was observed streaming `55 61` frames at
115200 baud; baud rate and sensor sample rate are different settings. Close the
manufacturer's app before opening the same serial port. If no new port appears,
try a known data cable, check the USB connection, and consult the manufacturer's
driver instructions for the USB chip actually enumerated by the computer.
USB availability does not imply that Bluetooth is paired or discoverable.

## Connect and record a labeled trial

Replace `YOUR_SCAN_IDENTIFIER` with the value after `address=`. The following
Mac command works on Windows by replacing `python3` with `py -3.12`:

```sh
python3 scripts/hardware/wt901_desktop.py run --address YOUR_SCAN_IDENTIFIER --node-id rack_1 --hz 50 --capture-path trial.jsonl
```

`--hz 50` is correct only when the sensor actually outputs **50 samples/second**.
The argument does not configure the sensor. Check its output rate using the
manufacturer's configuration utility and use the same rate here. Incorrect
timing invalidates duration and velocity estimates. Keep the sensor stationary
after connecting for calibration. Open `http://127.0.0.1:8765/health` to check
state, fresh samples, movement, and the local provisional rep count.

For a trial, have an observer use the terminal: type `start` and ENTER before
each set, press ENTER once after each visibly completed rep, and type `end` and
ENTER after the set. Start/end mark ground-truth boundaries; they do not reset
the detector. Reps and set markers are saved with sample timestamps in the
JSONL file. Use a new filename per trial because captures append. Press Ctrl+C
to stop. Keep trial files private: they contain raw motion data.

Local rep detection and health work without a reachable MQTT broker. Sending
provisional rep events to Edge Athlete requires explicit opt-in:

```sh
python3 scripts/hardware/wt901_desktop.py run --address YOUR_SCAN_IDENTIFIER --node-id rack_1 --hz 50 --base-url http://basestation --mqtt-host basestation --enable-provisional-reps
```

Use the base station's reachable hostname/IP and the node ID assigned to the
correct rack. The rack UI controls the workout's set start/end; this agent does
not infer workout intent merely from movement. Central `--socket-path`
enrollment uses Unix sockets and is not a Windows launch mode.

## Establish accuracy before trusting counts

Attach the sensor rigidly to the same point on the implement for every trial;
strap slack, rotation, impacts, and moving the sensor between exercises change
the signal. Collect independent labeled trials for each exercise and mounting
position, including slow/fast reps, pauses, partial reps, reracking, and handling
without lifting. Reserve some trials for validation after tuning. Compare
missed reps, extra counts, and per-set counts against video or an observer,
not just the total number of detections. A matching total can conceal both
misses and false positives. No physical accuracy percentage is established by
synthetic tests or by merely receiving Bluetooth packets. Velocity from this
IMU remains an estimate and requires separate reference validation.

If discovery fails, confirm Bluetooth is enabled, the sensor is advertising,
and the manufacturer's app/other computer has disconnected. On Mac 12.0–12.2,
update macOS; Bleak documents a scanning bug fixed in 12.3. On Windows use a
native console rather than an embedded GUI Python session. Run scan again
after changing adapter permissions or drivers.
[Bleak troubleshooting](https://bleak.readthedocs.io/en/latest/troubleshooting.html)

## This barbell setup

Mount the sensor firmly at the middle of the barbell, as planned. Keep the
orientation and attachment consistent between labeled trials. Test squats,
bench presses, and deadlifts separately if those are the intended lifts: pauses,
bar rolling, reracking, and different start/end positions can affect detection.
The present detector accepts rest-to-rest 3D translation cycles. A pause near
the farthest point of the cycle (for example the bottom of a squat) is held
instead of treated as a failed rep. Moving time is capped at eight seconds;
an abandoned hold at that farthest point times out after six seconds. It remains
provisional and is not yet qualified against labeled barbell sets.

On this Mac, the physical check on 2026-09-27 found `/dev/cu.usbserial-10`.
At 115200 baud it supplied 500 decoded samples in 10.05 seconds (49.73 Hz),
with zero provisional reps during that observation. A direct BLE connection
also succeeded and delivered 235 decoded samples in a five-second window.
These checks verify transport and decoding, not workout counting accuracy.
Port names and Bluetooth identifiers may differ on the next computer.

Replay a labeled trial using the installed environment:

```sh
venv/wt901/bin/python scripts/hardware/replay_capture.py trial.jsonl --hz 50 --match-tolerance-ms 1000
```

On Windows use `venv\wt901\Scripts\python.exe` instead. Replay reports
one-to-one timestamp matches, false positives, misses, precision, recall, counts
within explicitly labeled sets, and detections outside those sets. The matching
tolerance allows for observer reaction time; use the same tolerance when
comparing detector changes. Unlabeled motion cannot establish accuracy.
