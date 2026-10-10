# Working on Car Sniffer

## Project and environment

- Read `README.md`, `TOOLCHAIN.md` and the relevant `docs/` before changing behavior. `car_sniffer_codex_task.md` records the original requirements; `docs/verification.md` distinguishes tested behavior from bench limitations.
- The owner communicates in Russian. Keep progress reports concise and state what was actually verified.
- Windows / PowerShell; use `.venv/Scripts/python.exe` for Python commands and install dependencies only in `.venv`. Keep `requirements-lock.txt` consistent when changing dependencies.
- Run the desktop from source using `start.bat` or `python -m desktop`. The owner discontinued EXE packaging; do not spend time building PyInstaller bundles unless requested.
- Firmware uses hand-maintained CMake and pinned STM32CubeF4 HAL/CMSIS/USB sources. Bootstrap supplies ignored vendor code; do not commit vendor checkouts or require CubeMX generation.

## Hardware and firmware invariants

- MCU marking is STM32F407VET6. Physical Flash is 512 KiB; link the application within 256 KiB and reserve sectors 6/7 for dual-copy calibration. Keep within 512 KiB total Flash and 128 KiB DMA-capable SRAM, regardless of the programmer's reported capacity. DMA buffers must not use CCM.
- Preserve SWD access, the original backup in `backups/`, option bytes and external storage. Do not erase or modify these as part of routine development.
- Check `docs/pinout.md` before assigning pins. The board uses an 8 MHz HSE and USB-SLAVE; its external D+ pull-up requires the implemented USB disconnect pulse on initialization.
- Reset defaults: bridge off, CAN silent, capture off. Bitrate confirmation is explicit; Auto listens silently and must not guess on a quiet bus.
- CAN forwarding must remain independent of capture, display filters, Clear results and USB availability. Keep bounded queues, deadlines, visible loss counters and bounded recovery attempts.
- The analog range GPIO is open-drain: low enables R2=10k, Hi-Z releases R2. Revised input: R1=100k to VREF, R3=47k; scale factors 6.17 and 1.47, intercept -0.47*VREF. Reset is Hi-Z; do not describe the divider as safe for 15 V during reset. Analog protection and accuracy remain bench work.
- Internal CAN loopback is not evidence of physical delivery, ACK, arbitration or transceiver operation. Do not connect TX outputs together for an improvised CAN bus.
- Discover the connected COM port; COM8 is a recorded observation, not a permanent identity. Avoid hardware commands while the GUI owns the port. Leave bench tests with bridge off, CAN silent and capture off.

## Desktop behavior and design

- Preserve the owner's layout: graphs and CAN each occupy half the main area; CAN A and B are two columns side by side. General controls and CAN filters are in the 190 px right sidebar; channel/range checkboxes are left of the plots; status is at the bottom.
- Maintain readable dark colors, including native Windows caption where supported. No axis titles; time tick labels appear on the bottom plot.
- Wheel over a plot zooms voltage only; wheel over the time axis zooms time for all linked channels. Capture follows the newest data while preserving the selected span. Stopped plots permit browsing without timer updates resetting their view.
- Keep acquisition outside the Qt thread and memory bounded. Current limits: 20000 CAN rows per side, 6000 analog points per channel, 4096 queued protocol envelopes and 16000 raw calibration samples. Any limit change must update documentation and related controls.
- Capture stop does not stop the bridge; Clear results only clears the display. Keep these semantics explicit.
- C and Python packet formats must agree. Only the standalone `calibrate.bat` utility measures/uploads/persists calibration. Firmware applies it before averaging and restores dual CRC-protected Flash slots at boot; the main app must not read/upload calibration. Wizard steps: GND both modes, about 2.0 V released, about 10.0 V divided, with editable actual multimeter readings. Preserve reserved slots during firmware updates.

## Validation and Git

- For firmware/core/protocol changes, run `scripts/test-native.ps1`, `.venv/Scripts/python.exe -m pytest -q` and the ARM CMake build, or `scripts/verify.ps1`. Run hardware checks when the board is available and the change warrants them; report untested physical scenarios honestly.
- For GUI changes, run the relevant GUI tests and use `scripts/gui_smoke.py` when visual or live-update behavior changes. Inspect the screenshot when reviewing layout. Do not add tests that merely duplicate a trivial cosmetic edit.
- Keep `README.md` and behavior/protocol/pinout documentation aligned with changes. High-load repaint performance is a measured limitation, not a guaranteed 25 Hz.
- Before committing, inspect the staged paths and diff. Exclude virtual environments, build output, vendor trees, local flash backups and temporary files. Never force-push or discard unrelated owner changes as routine cleanup.

- Main GUI labels the range checkbox `DIV`, omits calibration/factory-default information, and excludes capture/range/USB service events from CAN tables. Keep CAN fault events. The standalone wizard reads current coefficients from firmware and displays `y=a*x+b` with x=raw*3.3/4095 volts and ranges `div off` / `div on`; factory defaults are an intentional valid model.
