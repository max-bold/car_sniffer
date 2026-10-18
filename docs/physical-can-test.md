# Physical CAN bench test

This diagnostic build is for exactly two external transceivers on one common,
properly terminated CAN segment: CANH to CANH, CANL to CANL and common GND.
Use the original PB8/PB9 and PB12/PB13 wiring. Disconnect the desktop GUI.
Do not enable the bridge on this common bus. This tests transceiver delivery
and ACK in both directions, not a bridge between two independent segments.

Build separately from the normal application:

```powershell
cmake -S firmware -B firmware/build-physical -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake -DCS_PHYSICAL_CAN_TEST=ON
cmake --build firmware/build-physical
```

Program only application sectors, preserving calibration sectors 6/7 and
option bytes. Reset still starts with bridge off, capture off and CAN silent.
In this build only, command 9 (`LOOPBACK_TEST`) explicitly starts a physical
test instead of silent internal loopback; do not run the ordinary hardware
smoke script against this diagnostic build.

```powershell
.venv/Scripts/python.exe -m scripts.physical_can_test --output docs/physical-can-hardware.json
```

The script explicitly configures both bitrates and capture. Firmware sends
32 frames per command and requires successful hardware transmission (TXOK),
exact reception on the opposite controller, no unexpected reception and no
CAN errors. Cases cover standard/extended IDs, DLC 0..8 and RTR. The host
independently checks received IDs, flags, lengths, payload and direction.
Both directions run at 83.333, 100, 125, 250, 500 and 1000 kbit/s (384 frames).
Firmware bounds each frame wait at 100 ms and returns both controllers to
silent after each command. The host stops capture and keeps the bridge off
on completion or failure. Restore the normal application after the test.

A successful report is bench evidence for this wiring and short exchange;
it does not establish sustained load, arbitration between external nodes,
two-segment forwarding, automotive protection or oscillator accuracy.
