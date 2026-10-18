# Verification status

Historical baseline date: 2026-10-10. Later dated entries record subsequent changes. The fixed-divider revision at the end supersedes earlier two-range calibration descriptions. The three evidence levels below are deliberately separate.

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

- ARM GCC/CMake/Ninja build succeeds for F407VE; application Flash256 KiB plus two reserved128 KiB calibration slots, SRAM128 KiB, no DMA CCM use. Current build is about33 KiB Flash,79 KiB reserved SRAM including heap/stack.
- Desktop runs from source in `.venv`. EXE packaging was stopped at the owner's request; it is not a supported or verified delivery artifact. A diagnostic console bundle ran, but the windowed bundle did not pass its startup check.
- Real two-segment bridge delivery, arbitration under load, no-ACK and bus-off recovery, directional fault containment while USB is disconnected, silent Auto on known/unsupported active bitrates: implemented but **not hardware validated** without external CAN nodes/transceivers.
- HAL mailbox, error and recovery paths are compiled; native engine tests do not simulate bxCAN registers or prove these physical scenarios.
- Electrical input safety, D1/D2 model, ADC accuracy, source settling and physical sine calibration remain unverified. Do not apply15 V during reset/Hi-Z startup.
- CubeMX generation has not been used or verified; the project does not depend on it. No vehicle tests or automotive qualification.

At the end of the earlier hardware checks, the board was left with bridge off, both CAN controllers silent, capture stopped, range control low (nominal1:5). Disconnect/reconnect may reset MCU and creates a new boot/time session. The external divider still defaults to unity during MCU reset despite its running firmware setting.

## Revised input and standalone wizard

New sources implement nominal100k/47k/10k bias compensation, linear zero/gain, commands10–12 and dual-slot Flash persistence. Native tests cover nominal modes, fractional zero, CRC corruption and interruption before every programmed Flash word. Wizard tests cover all three steps, sixteen profiles and acknowledged persistence. These are simulated Flash/input tests, not physical calibration or board power-cut validation. Earlier hardware JSON reports predate these changes.

Latest source verification:15 Python tests pass, native engine/Flash simulations pass, ARM build33848 bytes application Flash and80872 bytes reserved SRAM. The revised firmware was programmed and readback-verified after the owner confirmed all analog inputs were floating. Repeated hardware smoke passed: eight100 Hz channels, both silent loopbacks, no observed CRC failures/gaps. Both range formulas were checked against streamed raw means (version0/FACTORY_DEFAULTS), with error below0.1 mV; see `nominal-coefficients-hardware.json`. This verifies arithmetic, not physical input accuracy. Final capture/bridge off, CAN silent, all ranges divided. Hardware Flash calibration persistence remains untested; no measured profiles were written.

Coefficient query/UI update: revised firmware programmed with readback verification. The standalone wizard read all16 factory-default coefficient sets over COM8 (no CRC failures/sequence gaps); see `coefficients-readback-hardware.json` and `calibration-current.png`. Main GUI real-device smoke rendered all8 streams with zero CAN rows when only service events were present. New C/Python codec vectors include kind10; wizard handles response-before-data ordering and rereads profiles after saves.

## Analog wiring reorder, 2026-10-18

AIN1..AIN8 now map to PC0, PC1, PC2, PA1, PA2, PA3, PA4, PA5; divider controls map to PD15..PD8. Native C tests passed. The first Python run had one failure in the existing GUI stopped-view timing check; a full repeat passed all 16 tests. Normal ARM build (`CS_PHYSICAL_CAN_TEST=OFF`) uses 33932 bytes application Flash and 80872 bytes reserved SRAM; it was programmed and readback-verified. Calibration sectors 6/7 were read before and after programming and their SHA256 hashes matched.

Live ADC SQR1/SQR2/SQR3 readback was 0x00700000/0x000000A4/0x0620B16A, confirming eight conversions in channel order 10,11,12,1,2,3,4,5. USB smoke on COM4 received 201 points per channel in two seconds with 10000 us steps; both silent internal loopbacks passed, with zero CRC failures and sequence gaps. Reported telemetry loss was 1. This does not verify external analog wiring or voltage accuracy. Divider selection uses bit 15 minus the zero-based channel index in the compiled firmware; individual physical divider switching was not measured. Stored calibration remains indexed by logical channel and requires checking after rewiring. Final bridge/capture off, CAN silent, all ranges divided.

## GND calibration acceptance, 2026-10-18

With the owner reporting all external inputs grounded, raw acquisition on COM4 reproduced the wizard rejection: AIN3..AIN5 had approximately3.2..4.1 ADC counts standard deviation, above the former3-count limit, while initial/final100 ms means stayed close. All16 channel/range acquisitions had1600 samples and no timestamp gaps, packet sequence gaps or CRC failures. The revised desktop accepts raw std<=6 counts and separately rejects a span>3 counts between consecutive block means, without detrending or dropping samples. New regression checks distinguish sample noise from drift; all8 calibration/wizard tests passed.

The actual revised CalibrationWindow then completed stage1 (GND) against the board:1600 samples for each of16 channel/range combinations, raw std approximately1.74..3.70, block mean spans0.34..0.94 counts, zero packet gaps/CRC failures/host drops. No coefficients were uploaded or saved. Gain stages and physical voltage accuracy were not validated. All ranges returned to divided; bridge and capture remained off. Local diagnostic reports are in ignored `tmp/calibration-ground-check.json` and `tmp/calibration-wizard-ground-check.json`.

## Factory calibration reset, 2026-10-18

The standalone wizard now offers a confirmed factory-coefficient reset using command14. Firmware commits a newer empty calibration record to the inactive slot and only reloads defaults into RAM after successful Flash verification. Native NOR simulation tested interruption before every programmed reset word, reload of defaults after a completed reset, and saving a measured calibration after reset. Existing interrupted-save/CRC checks also passed. All18 Python tests passed, including cancellation, acknowledged reset, coefficient readback and wizard state. ARM normal build succeeded (34016 bytes application Flash,80872 bytes reserved SRAM). Demo GUI smoke passed with zero observed host packet losses/sequence gaps; the wizard screenshot was inspected. Factory-reset execution on real Flash has not been performed as part of this change.

The normal build was subsequently programmed and readback-verified on the connected board. SHA256 comparison of all256 KiB in calibration sectors6/7 before and after the firmware update matched. USB smoke on COM4 passed all8 analog streams and both silent internal loopbacks, zero CRC failures/sequence gaps, telemetry loss1. The updated wizard read all16 existing measured profiles (source1) back successfully. The factory reset itself was not executed. Final bridge/capture off, CAN silent, all ranges divided.

## Fixed-divider revision, 2026-10-18

The software now requires R2=10k permanently grounded, with47k from AIN and100k to VREF; shunt zeners are removed. PD8..PD15 are unused, with no GPIO configuration/writes or range-switch function. ADC order remains PC0,PC1,PC2,PA1..PA5. The main GUI omits DIV and ignores old range preferences. Calibration is GND then approximately10 V, with eight active profiles and source coefficients a=6.17/b=-1.551 by default. Packet layouts remain unchanged, with range fixed at1; removed range0 commands/profiles are rejected.

CAL2 stores eight profiles and deliberately ignores CRC-valid CAL1 records without modifying Flash during boot. Native tests cover this rejection/preservation, fixed-divider nominal0/2/15 V conversion, rejection of a removed range, per-sample calibrated conversion, and dual-slot save/reset interruption. All21 Python tests passed, including two-step wizard, eight-profile readback/persistence, old-firmware rejection and ignoring saved narrow-range GUI settings. ARM normal build succeeded:33520 bytes Flash,76512 bytes reserved SRAM. Demo GUI smoke offered12000 frames/s for5 s, reached20000 rows per side with visible eviction, retained502 analog points per channel and observed zero host packet drops/sequence gaps. New main/wizard screenshots were inspected.

The fixed-divider firmware has not yet been programmed or tested on the rebuilt hardware. No hardware commands or Flash writes were performed during this revision while the owner was modifying the circuit. Earlier electrical/hardware reports describe the previous hardware. New accuracy and protection measurements remain pending.

After the owner confirmed the fixed-divider hardware was ready, the normal firmware was programmed and readback-verified. Calibration sectors6/7 matched byte-for-byte before/after programming; their legacy CAL1 contents were not applied. The updated wizard read exactly eight factory-default profiles (range1, source0/version0, displayed a=6.17/b=-1.551). RCC AHB1ENR read0x00500007, with the GPIOD clock disabled. USB smoke on COM4 received201 points per channel over2 s,10 ms output steps, both silent internal loopbacks passed, zero CRC failures/sequence gaps, telemetry loss1. Final bridge/capture off and CAN silent. No new calibration coefficients were measured or written, and input voltage accuracy was not established by this smoke test.

The owner subsequently reported successful operation and agreement with the laboratory supply's displayed voltage to hundredths of a volt at tested points up to15.5 V. Reference-instrument uncertainty and the complete error budget were not measured, so this is reported bench agreement rather than a guaranteed accuracy specification. A later screenshot showed synchronous approximately25..30 mV changes across all eight channels near10.7 V; the source, reference and ground contributions were not isolated.
