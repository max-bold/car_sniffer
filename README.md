# Car Sniffer

STM32F407VET6 firmware and Windows desktop MVP for two Classic CAN sides (A/CAN1, B/CAN2) and eight analog inputs. The board is STM32 F4VE with 8 MHz HSE, USB-SLAVE and ST-Link/SWD. The firmware linker is deliberately limited to **512 KiB Flash / 128 KiB DMA-capable SRAM**.

## Run

From the repository root in PowerShell:

```powershell
.\scripts\bootstrap.ps1
.\.venv\Scripts\python.exe -m desktop --demo
# Real device: omit --demo, select its COM port and click Connect
.\.venv\Scripts\python.exe -m desktop
```

After setup, double-click `start.bat` to launch from the project's `.venv`. `start.bat --demo` opens the simulated device. Python packages belong in `.venv`; see [TOOLCHAIN.md](TOOLCHAIN.md) for CLI prerequisites. Native C tests additionally require MSVC Build Tools.

## Desktop controls

The main area is split equally between eight dark analog plots and two side-by-side CAN tables. Channel enable and range checkboxes sit left of the plots; the checked range is 0–15 V (nominal 1:5), unchecked is 0–3.3 V. Connection, bitrates, capture, calibration and independent CAN filters occupy the right sidebar. Status and diagnostics appear at the bottom.

During capture, the time axis follows new samples. Set **Time window** (0.1–60 s), or turn the wheel over the bottom time scale to zoom all channels together. The wheel over a plot changes only voltage scale. After stopping capture, drag the graphs to browse retained data and use the same zoom controls. Each channel retains at most 6000 points (about 60 s at 100 Hz); older points are removed. Time labels appear only on the bottom plot.

Apply the bitrate for each side before enabling the bridge. Start/Stop capture is independent of bridge state. Clear results clears only the display. There is no session recording/export feature. Demo data is simulated and identified in the device selector.

## Firmware build and programming

```powershell
cmake --preset debug -S firmware
cmake --build firmware/build
STM32_Programmer_CLI -c port=SWD -d firmware/build/car_sniffer.elf -v -rst
```

Run the desktop from source in `.venv`; EXE packaging was discontinued at the owner's request. The experimental packaging script and any `dist` output are not a verified release.

## Verify

```powershell
.\scripts\test-native.ps1   # MSVC Build Tools, native C engine and codec DLL
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.gui_smoke --seconds 10 --fps 12000
.\.venv\Scripts\python.exe -m scripts.hardware_smoke --output docs/hardware-smoke.json
```

The hardware smoke test only uses silent internal loopback. It does not enable the bridge or send CAN traffic on pins. Firmware generation is hand-maintained CMake + official STM32CubeF4 HAL/CMSIS/USB middleware; CubeMX and an `.ioc` are not required. Dependencies are pinned in `requirements-lock.txt` and to CubeF4 v1.28.1 commit `83778d5c95cb01695c7facbf095db3ab445532ea`; bootstrap checks out its pinned HAL/CMSIS submodules.

Read [pinout and electrical limits](docs/pinout.md), [protocol](docs/protocol.md), [calibration](docs/calibration.md), [behavior and limits](docs/behavior.md), and [verification](docs/verification.md) before wiring a bench. No vehicle tests have been performed. Do not connect a vehicle to this prototype before verifying protection, power/ground and termination.

Original board Flash was backed up locally to `backups/factory-flash.bin` before first programming. It is intentionally excluded from Git. Firmware does not touch option bytes, external SPI Flash, SD storage or MCU calibration Flash.
