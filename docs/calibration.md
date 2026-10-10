# Standalone analog calibration

Run `calibrate.bat` or `.venv/Scripts/python.exe -m desktop.calibrate`. Close/disconnect the acquisition application first; only one program may own the COM port. The utility stops bridge/capture and selects divided mode. The acquisition application never reads or uploads calibration files.

## Three steps for all eight inputs

1. Connect **AIN1–AIN8 to GND**. Press Measure. Zero is measured in both ranges for all eight inputs.
2. Connect **AIN1–AIN8 to approximately 2.0 V**. Enter the actual multimeter reading (default **2.0000 V**). Measure gain without the divider. All inputs return to divided mode before the next step.
3. Connect **AIN1–AIN8 to approximately 10.0 V**. Enter the actual multimeter reading (default **10.0000 V**). Measure divided-range gain. Disconnect the source or connect the inputs to GND, then click **Write to device**.

Use a stable low-impedance source capable of supplying all eight networks, with a common GND. Keep the MCU powered; do not reset with 10 V applied. One channel is sampled at a time, at1600 samples/s for1 s after a100 ms settling delay. The zero step takes about22 s; each gain step about11 s. Do not change wiring during a step.

Require at least90% of expected samples, continuous625 us timestamps, raw std<=3 ADC counts, no clipping (codes<=2 or>=4093), and reference span>=100 ADC counts. A clipped zero is rejected: the revised VREF bias should lift zero above the ADC rail. Missing packets or command rejection abort the wizard; reconnect/reset it to start again.

Each of sixteen profiles stores fractional zero ADC code and positive volts/count:

`Vin = (raw - zero) * gain`, `gain = Vreference / (mean_reference - mean_zero)`.

Zero is not rounded or clamped; small negative results near zero are retained and may carry the selected-range flag. This affine model extends beyond the two measured anchors and assumes linearity. Two-point calibration does not establish accuracy near diode conduction or across the entire range. Clipping still invalidates displayed traces. Every sample is converted before the16-sample average.

## Nominal defaults for the revised input

[Revised input schematic](analog-input-biased.png). R1=100 kΩ from ADC node to VREF; R3=47 kΩ from AIN to ADC node; R2=10 kΩ from ADC node to the open-drain GPIO; C1=1 nF. Assume VREF=VDDA=3.3 V, negligible clamp leakage and low source impedance.

With R2 released: `Vin = (1+R3/R1)*Vadc - (R3/R1)*VREF = 1.47*Vadc - 1.551 V`.

With GPIO low: `Vin = (1+R3/R1+R3/R2)*Vadc - (R3/R1)*VREF = 6.17*Vadc - 1.551 V`.

At12 bits, `Vadc=raw*3.3/4095`:

| Mode | Nominal zero, counts | Nominal gain, V/count |
|---|---:|---:|
| R2 released, 0–3.3 V UI range | 1309.285714 | 0.001184615385 |
| R2 grounded, 0–15 V UI range | 311.936791 | 0.004972161172 |

Without saved calibration firmware uses these formulas and reports FACTORY_DEFAULTS/version0. The board is usable with lower accuracy. Resistor tolerance, reference error, GPIO low voltage, leakage and source impedance affect accuracy. Old40k/10k coefficients are incompatible. If the VREF shown in the input circuit differs from VDDA, review the nominal model and calibrate.

## Device persistence and firmware updates

Only the utility uploads profiles. It awaits all sixteen acknowledgements, then asks firmware to save. Flash sectors6/7 at `0x08040000` and `0x08060000` (128 KiB each) are excluded from the application linker region. Firmware erases only the inactive slot, writes a versioned generation/CRC32 record, then writes the commit marker last. Boot selects the newest valid copy. Interrupted writes preserve the previous copy; interrupted first-ever writes leave nominal defaults. Save is rejected if capture/bridge is active or profiles are incomplete.

The utility saves an optional audit report in `%LOCALAPPDATA%/CarSniffer/calibration-report-<uid>.json` after the Flash acknowledgement. The board does not need that file, the PC or the main application to apply calibration. Legacy desktop JSON profiles are not imported. Legacy table commands remain supported, but the wizard creates affine profiles only. The capture application's ordinary channel/bitrate preferences use separate Qt settings.

The application is now limited to256 KiB within the physical512 KiB. Use sector-aware firmware download; **mass erase removes calibration**. Persisted-format compatibility is checked using magic/size/CRC; changes to the stored structure require explicit format migration. Do not erase option bytes or the original local Flash backup.

## Verification limits

Native tests execute actual storage code against simulated NOR Flash, with failure before every programmed word and CRC corruption. Wizard tests exercise all three steps and acknowledged saves. Revised-board accuracy, actual clamp behavior and physical power-cut endurance still require a source/voltmeter bench. Firmware timing is provisional; calibration does not establish electrical safety. Reset releases the range GPIO and does not guarantee a safe15 V input range.

## Current coefficients in the wizard

On connection the utility reads all16 active profiles from the device (command13, packet kind10). The table labels are `div off` and `div on`. Displayed coefficients use `y=a*x+b`, with `x=raw ADC*3.3/4095` in volts and `y=AIN voltage` in volts; the stored/raw-protocol gain is volts per ADC count, so displayed `a=gain*4095/3.3`, `b=-zero*gain`. Before connecting the table explicitly previews factory defaults (a1.47/6.17,b-1.551); after connecting it shows actual readback. New measured coefficients are colored until written; after saving coefficients are read back again. Legacy nonlinear tables are labeled as tables rather than presenting a false single straight line.
