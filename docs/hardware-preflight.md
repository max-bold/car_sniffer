# Hardware preflight, 2026-10-10

## Confirmed and observed

- Owner confirmed package marking STM32F407VET6. Use 512 KiB Flash for firmware linking, despite CubeProgrammer reporting 1 MiB. SWD device ID alone does not establish exact ordering code.
- CubeProgrammer and OpenOCD connected successfully over ST-Link SWD. Target supply approximately 3.25 V. No firmware was written.
- Supplied STM32_F4VE_SCHEMATIC.PDF shows Y2 = 8 MHz HSE and Y1 = 32.768 kHz LSE. These are schematic values, not measured frequencies.
- USB-SLAVE J4 uses PA11/DM and PA12/DP through 22 ohm resistors; external 1.5 kohm DP pull-up is shown. USB VBUS feeds board 5 V through R25. Avoid simultaneous independent power sources; ST-Link can remain attached for SWD with its power output disconnected.
- PA9 is routed as UART1 TX, not USB VBUS sensing in this schematic. USB device configuration must account for this.
- Existing board connections include LEDs PA6/PA7, button PA0, buttons PE3/PE4, SPI flash PB3/PB4/PB5 and PB0, SDIO PC8-PC12/PD2, LCD and NRF headers. Final pin assignment must avoid conflicts with fitted modules.

## Analog divider supplied as AIN.png

- R3 = 40 kohm, R2 = 10 kohm, C1 = 1 nF; shunt diode network is connected to the ADC node.
- Control low gives nominal VADC = VIN/5. Control Hi-Z gives nominal unity transfer only while diode and GPIO leakage are negligible. Configure control as open-drain, no pull-up or pull-down.
- Approximate linear RC time constants: low state 8 us; Hi-Z 40 us. These do not establish actual settling time with diode nonlinearity and ADC loading.
- Reset leaves GPIO Hi-Z: the hardware does not default to the 0-15 V divider state. Software cannot guarantee this state during reset or before initialization. Do not apply high input voltage until protection and startup behavior are verified.
- A 3.3 V shunt diode is not proof of ADC absolute-maximum compliance. Diode part numbers, leakage and clamp voltage at actual current remain unknown.

## Debugging without CAN transceivers

Start with internal bxCAN loopback, no inter-controller wiring. Simple cross-connected TX/RX does not emulate wired-dominant CAN or correctly return each transmitter's bus state. Never tie push-pull TX outputs together. A separate 3.3 V logic bus emulator would need a combined dominant-low signal fed to both RX inputs; this cannot validate the physical CAN layer or two independent bridge segments.

## Toolchain

Git 2.43.0, CMake 4.3.1, Ninja 1.13.2, ARM GCC 14.3.1, ARM GDB 15.2.90 and OpenOCD 0.12.0+dev launch. A temporary Cortex-M4 C executable compiled and linked using CMake/Ninja; this was not an STM32 HAL firmware build. CubeMX executable exists (file version 6.18.1-RC2); code generation has not been verified.
