# Standalone analog calibration: fixed divider

Run `calibrate.bat` or `.venv/Scripts/python.exe -m desktop.calibrate`. Disconnect the main acquisition application first; only one program may own the COM port. Use the fixed-divider firmware and updated desktop together. Older firmware is rejected when it returns a removed range during coefficient readback.

## Hardware and two steps

All eight channels use R3=47k from AIN to the ADC node, R1=100k from VREF+ to the node, R2=10k permanently from the node to GND, and C1=1nF to GND. Disconnect the former PD8..PD15 divider wires and remove the shunt zeners. There are no range GPIO controls or DIV checkboxes. See [pinout](pinout.md).

1. Connect **AIN1..AIN8 to board GND**, then press Measure. The wizard measures eight zero offsets.
2. Connect **AIN1..AIN8 to approximately10.0 V**, enter the actual multimeter reading, then press Measure. The wizard measures eight gains.
3. Disconnect the source or ground the inputs, then press **Записать в устройство** to upload the eight profiles and persist them in Flash.

Use a stable low-impedance source and common ground. Each channel is sampled separately at1600 samples/s for1 s after100 ms settling; each measurement step takes about11 s. Do not change connections during a step. The physical divider is permanent during reset, but the current hardware has no fitted Schottky protection and is not validated against faults, negative voltage or input applied without MCU power.

Require at least90% of expected samples, continuous625 us timestamps, raw std<=30 ADC counts, no clipping (codes<=2 or>=4093), and reference span>=100 ADC counts. Source drift is checked separately: split the samples into up to ten consecutive blocks of at least160 samples (100 ms at1600 Hz); the largest minus smallest block mean must be<=84 ADC counts. All samples contribute to the calibration mean; no detrending or outlier removal is performed. This acceptance check does not establish voltage accuracy. A clipped zero is rejected: the revised VREF bias should lift zero above the ADC rail. Missing packets or command rejection abort the wizard; reconnect/reset it to start again. Measurement validation errors identify the channel/range and measured ADC statistics.

Each channel stores fractional zero and positive volts/count: `Vin = (raw-zero)*gain`, `gain = Vreference/(mean_reference-mean_zero)`. Every sample is converted before16-sample averaging. Two-point calibration corrects offset and slope; it does not compensate nonlinear protection or prove accuracy over the whole range.

## Defaults

Assuming VREF=VDDA=3.3 V: `Vin = 6.17*Vadc - 1.551 V`, where `Vadc=raw*3.3/4095`. Nominal zero is311.936791 counts and gain0.004972161172 V/count. The UI shows `y=a*x+b`, with x in ADC volts: factory a=6.17, b=-1.551 V. One ADC count corresponds to approximately4.97 mV at AIN. Values at the ADC are approximately0.251 V for AIN=0 V and2.682 V for AIN=15 V.

On connection command13 returns **eight** coefficient records with the reserved wire range field fixed at1. The table shows one a/b pair per channel. Measured drafts are highlighted until written; saved profiles are reread from the device. The main acquisition app does not query or upload calibration.

## Persistence, compatibility and reset

Only the standalone utility uploads/saves calibration. Accepted uploads apply in RAM immediately. Save is rejected while bridge/capture are active or any of the eight linear profiles is missing. Successful saves survive power cycles; no MCU reset is required.

Flash sectors6/7 at0x08040000 and0x08060000 are reserved128 KiB slots. CAL2 records contain eight profiles, generation, size, CRC and a commit marker written last. The inactive slot is erased; interrupted writes preserve the preceding CAL2 record. Factory reset commits a newer empty CAL2 record, then reloads nominal defaults. **Заводские коэффициенты…** requests confirmation and verifies all eight source0/version0 profiles after reset. **Сбросить мастер** only discards measurements in the utility.

**CAL1 records from the old two-range hardware are deliberately ignored, without erasing them at boot or during application programming.** The changed analog circuit requires new measurements; there is no automatic reuse of old divided-range profiles. On first boot without CAL2, nominal defaults are active. A later explicit save/reset writes only one calibration slot using the dual-copy scheme. Never mass-erase or change option bytes as part of a firmware update.

An optional audit report is saved to `%LOCALAPPDATA%/CarSniffer/calibration-report-<uid>.json` after acknowledged persistence. It is not needed by the device or main app; legacy reports are not imported automatically.

## Verification limits

Native tests simulate NOR Flash interruption, factory reset and rejection of CRC-valid CAL1 data without modifying Flash on load. Wizard tests exercise GND/10 V, eight uploads, acknowledged persistence/readback and factory reset. Physical accuracy/protection of the revised hardware still requires bench measurement.

The acceptance limits30/84 ADC counts were derived as three times maximum noise/block-mean span from5 s acquisitions with the owner reporting2 V on all inputs, before removing zeners and range control. They are retained as acceptance tolerances, not a measured accuracy guarantee for the rebuilt circuit.
