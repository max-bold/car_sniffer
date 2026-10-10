# Verification status

Date: 2026-10-10. The three evidence levels below are deliberately separate.

## Executed on the connected F4VE board

- ST-Link/SWD connectivity and approximately 3.27 V supply with USB-SLAVE power and ST-Link power output disconnected.
- Original Flash read to local `backups/factory-flash.bin` (1 MiB read because the programmer reports this capacity). Owner confirmed STM32F407VET6 marking; all new firmware links within512 KiB. Exact silicon revision remains unidentified (DBGMCU_IDCODE read0x0009A413, not one of the documented ES0182 revision IDs); do not assume a known revision's exceptions.
- ELF download and readback verification, then repeated GDB/OpenOCD programming/debugging. No option-byte changes.
- USB CDC enumerates as VID0483/PID5740 on **COM8**. These are development example IDs, not an assigned commercial USB identity.
- `scripts/hardware_smoke.py`: status/command responses, eight analog streams, 10,000 us between output windows; about200 samples per channel in a two-second read; silent internal loopback on CAN1 and CAN2; capture stop; final bridge off/silent mode; zero observed transport CRC failures/sequence gaps. See `hardware-smoke.json`.
- `scripts/hardware_extended.py`: byte-fragmented command, corrupted command CRC not executed, oversized-length resynchronization, refusal of unconfirmed bridge, independent disable of channel0, >=500 raw samples with625 us spacing, visible bounded telemetry loss after closing/reopening the COM port while capture continued, silent Auto unknown with no CAN traffic. See `hardware-extended.json`.
- `scripts/gui_smoke.py --port COM8`: all eight streams rendered with no host packet loss or sequence gaps. ADC pins were floating/disconnected; displayed voltage is **not an accuracy measurement**. See `gui-com8-smoke.json` and `gui-com8.png`.

ADC frequency evidence includes streamed counts/timestamps and configured timer/DMA operation. Absolute oscillator accuracy and analog sample aperture have not been measured with an oscilloscope/reference clock. Internal loopback does not test transceivers, physical CAN, ACK, arbitration or isolation.

## Native C / Python / GUI simulation

`scripts/test-native.ps1` builds the actual portable C sources with installed MSVC. Native engine assertions cover both forwarding directions, standard/extended/RTR frames, identical RX on both sides, queue ordering/overflow/expiry, capture-stop independence, no USB dependency, nonlinear per-sample conversion, clipping and settling. It also builds a C codec DLL.

`python -m pytest -q`: **12 tests pass**. C/Python byte-for-byte packet vectors (including full payloads) and C callbacks are checked through the DLL; tests cover fragmentation, concatenation, noise, length/CRC rejection, sequence gaps/wrap/reset, profile monotonicity/device binding, DC instability/clipping, known sine nonlinearity/offset/phase/delay/noise/branch rejection, GUI model/filter/TX linkage, demo start/stop/clear and bounded worker lifecycle. Run native tests first; the cross-language test is explicitly skipped if its DLL is unavailable.

Demo GUI load runs offer12,000 frames/s across both tables plus8 analog streams. Both tables reach the20,000-row cap, old-row eviction is visible, and no host packet loss/sequence gaps were observed. Source GUI timer is40 ms. On this offscreen Windows test platform high CAN-table load reduces actual render/update frequency to roughly9–11 Hz; real ADC-only USB test remained near25 Hz. This is a current **performance limitation**, not a claim of25 Hz repaint under maximum traffic. Acquisition continues at100 Hz/channel independently. See generated GUI JSON reports; exact measurements vary with simultaneous builds and test load.

## Build only / still requires a bench

- ARM GCC/CMake/Ninja build succeeds for F407VE; Flash512 KiB, SRAM128 KiB, no DMA CCM use. Current build is about31 KiB Flash,76 KiB reserved SRAM including heap/stack.
- Desktop runs from source in `.venv`. EXE packaging was stopped at the owner's request; it is not a supported or verified delivery artifact. A diagnostic console bundle ran, but the windowed bundle did not pass its startup check.
- Real two-segment bridge delivery, arbitration under load, no-ACK and bus-off recovery, directional fault containment while USB is disconnected, silent Auto on known/unsupported active bitrates: implemented but **not hardware validated** without external CAN nodes/transceivers.
- HAL mailbox, error and recovery paths are compiled; native engine tests do not simulate bxCAN registers or prove these physical scenarios.
- Electrical input safety, D1/D2 model, ADC accuracy, source settling and physical sine calibration remain unverified. Do not apply15 V during reset/Hi-Z startup.
- CubeMX generation has not been used or verified; the project does not depend on it. No vehicle tests or automotive qualification.

The board is left with bridge off, both CAN controllers silent, capture stopped, range control low (nominal1:5). Disconnect/reconnect may reset MCU and creates a new boot/time session. The external divider still defaults to unity during MCU reset despite its running firmware setting.
