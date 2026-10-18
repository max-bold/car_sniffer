# Board configuration and electrical limits

All wiring choices are in `firmware/include/board.h`. STM32F407VET6, LQFP100. Pin choices are checked against the supplied F4VE schematic and DS8626 Rev 12, Table 7 and AF9 mapping. External LCD/NRF modules must be absent. Inspect the actual PCB revision before connecting external circuits.

| Function | GPIO | MCU package pin | AF / ADC | Connection and limits |
|---|---|---:|---|---|
| CAN A RX | PB8 | 95 | AF9 CAN1_RX, FT | TJA1050 A RXD; no internal pulls |
| CAN A TX | PB9 | 96 | AF9 CAN1_TX, FT | TJA1050 A TXD, 3.3 V push-pull |
| CAN B RX | PB12 | 51 | AF9 CAN2_RX, FT | TJA1050 B RXD; no internal pulls |
| CAN B TX | PB13 | 52 | AF9 CAN2_TX, FT | TJA1050 B TXD, 3.3 V push-pull |
| USB D- | PA11 | 70 | AF10 OTG_FS | Board USB-SLAVE, 22 ohm series |
| USB D+ | PA12 | 71 | AF10 OTG_FS | Board USB-SLAVE, 22 ohm series, external 1.5 kohm pull-up |
| AIN4 | PA1 | 23 | ADC1_IN1 | Divider MCU_ADC, 0..VDDA only |
| AIN5 | PA2 | 24 | ADC1_IN2 | Same |
| AIN6 | PA3 | 25 | ADC1_IN3 | Same |
| AIN7 | PA4 | 29 | ADC1_IN4 | Same; DAC disabled |
| AIN8 | PA5 | 30 | ADC1_IN5 | Same; DAC disabled |
| AIN1 | PC0 | 15 | ADC1_IN10 | Same |
| AIN2 | PC1 | 16 | ADC1_IN11 | Same |
| AIN3 | PC2 | 17 | ADC1_IN12 | Same |
| SWD | PA13 / PA14 | 72 / 76 | SWDIO / SWCLK | Preserved; common GND, ST-Link power output disconnected when USB powers board |

PB8/PB12 are FT digital inputs in the selected AF, not analog inputs. STM32 internal pulls are disabled; DS8626 Table 48 note 5 requires this above VDD+0.3 V. Do not drive 5 V RXD into an unpowered MCU: the FT absolute input limit is VDD+4 V, so 5 V violates it at VDD=0. Power the MCU before the transceivers or isolate their RXD during power sequencing. Board/module grounds must be common on an unisolated bench. FT does not imply automotive surge tolerance.

NXP TJA1050 TXD thresholds are VIH >=2.0 V and VIL <=0.8 V, compatible with 3.3 V STM32 GPIO at the small TXD load. TJA1050 supply must be 4.75..5.25 V. Verify actual module part and pinout; do not substitute CANH/CANL for RXD/TXD. Verify its S input is strapped for the intended mode. Silent behavior here comes from bxCAN, not an assumed module S setting.

## Fixed analog divider

Each ADC node connects to AIN through R3=47k, to VREF+ through R1=100k, to GND through R2=10k and to GND through C1=1nF. **Connect the lower end of every R2 directly to board GND. Disconnect the old PD8..PD15 connections.** These GPIOs are unused and are not configured or driven by this firmware. Analog input/channel ordering above is unchanged.

The single nominal input range is 0..15 V. With VREF=VDDA=3.3 V, `Vin = 6.17*Vadc - 1.551 V`; one ADC count corresponds to approximately4.97 mV at AIN. R2 remains grounded during reset; there is no GPIO-controlled divider transition.

The BZX55C3V3 shunt zeners are removed because they distorted the high-impedance input. Schottky protection has not been fitted. The resistor divider alone does not establish protection against negative inputs, overvoltage, transients or signals applied while the MCU is unpowered. The ADC node must stay within its electrical limits. Physical protection and accuracy remain bench work.

### VREF connection for analog input bias

According to sheet 1 of [STM32_F4VE_SCHEMATIC.PDF](../STM32_F4VE_SCHEMATIC.PDF), connect the VREF end of each external R1=100k bias resistor (one per analog channel) to **J2 pin 20, VREF+**. This is an external resistor connection, not an MCU GPIO pull-up.

| Header contact | Signal | Connection on the board |
|---|---|---|
| J2 pin 20 | VREF+ | MCU pin 21; connected through R11=0 ohm to VDDA, then through R34=0 ohm to 3V3 |
| J2 pin 19 | VREF- | MCU pin 20; connected through R35=0 ohm to GND |

VREF+ is therefore nominally 3.3 V from the board supply, not a separate precision reference or the internal VREFINT source. Use the connector pin numbers in the schematic to identify the contacts on the actual board.

## Clock and timing

The supplied schematic specifies Y2=8 MHz. PLL M=8, N=336, P=2, Q=7: SYSCLK/HCLK=168 MHz, APB1=42 MHz, APB2=84 MHz, USB=48 MHz, APB1 timer clock=84 MHz. HSE failure stops startup instead of silently using an inaccurate USB clock. Actual oscillator frequency has not been measured with an instrument.

CAN: 42 MHz / prescaler / 14 TQ; synchronization 1 TQ, BS1=11, BS2=2, SJW=1, sample point 85.714%. These choices are configurable code, not measured bus timing.

| Nominal kbit/s | Prescaler | Actual kbit/s | Error |
|---:|---:|---:|---:|
| 83.333 | 36 | 83.333333 | +0.0004% relative to integer command 83333 |
| 100 | 30 | 100 | 0 |
| 125 | 24 | 125 | 0 |
| 250 | 12 | 250 | 0 |
| 500 | 6 | 500 | 0 |
| 1000 | 3 | 1000 | 0 |

ADC1 clock=21 MHz (PCLK2/4), sample time initially 480 cycles plus 12 conversion cycles: about 23.43 us per channel, 187.43 us per eight-channel scan. TIM2 TRGO at exactly 1600 Hz (84 MHz / 52500). 16 scans produce one 10 ms window, 100 points/s/channel. Scan order is logical AIN1..AIN8: PC0, PC1, PC2, PA1, PA2, PA3, PA4, PA5 (ADC channels 10,11,12,1,2,3,4,5), not simultaneous. Timestamps identify the common window start/scan trigger, with channel offsets of approximately zero-based rank*23.43 us, not measured sample aperture. TIM5 is a 1 MHz 32-bit counter extended to 64 bits by its update ISR.

Stored calibration is indexed by logical channel. The fixed-divider firmware uses a new CAL2 record format and ignores CAL1 calibration from the former switching circuit. Updating the application preserves sectors6/7; new coefficients require fresh GND/10 V calibration.

R1=100k/R2=10k/R3=47k/C1=1nF gives an approximate7.6 us RC constant, excluding ADC/source effects. ADC sample time and startup settling (`BOARD_SETTLING_US=20000`) remain provisional bench parameters. DMA2 Stream0/Channel0 buffers stay in normal SRAM, never CCM.

## Termination and limitations

Each independent CAN segment needs its own topology and termination: normally 120 ohm at each physical end (approximately 60 ohm measured across an unpowered, fully connected segment). Check whether TJA1050 modules already contain 120 ohm and count those resistors. Do not add a terminator at every node. A bridge creates two segments; it does not electrically join them. The firmware provides no galvanic isolation.

Start CAN tests with internal silent loopback and no jumpers. A simple cross-connection TX->RX does not implement CAN bus feedback/ACK/arbitration. Never connect the two push-pull TX pins together. A logical bus emulator requires dominant-low combination fed back to both RX; it still cannot test physical CAN or two independent bridge segments.

## Primary sources and errata

- [DS8626 Rev 12, March 2026](https://www.st.com/resource/en/datasheet/stm32f407ve.pdf): Table 7 (FT and LQFP100 pins), Table 9 AF mapping, Tables 11/48/49 electrical limits.
- [RM0090](https://www.st.com/resource/en/reference_manual/dm00031020-stm32f405-407-415-417-437-455-469-application-note-stmicroelectronics.pdf): bxCAN, ADC/DMA, timers and USB.
- [TJA1050](https://www.nxp.com/docs/en/data-sheet/TJA1050.pdf): TXD thresholds and 5 V supply.
- [ES0182 Rev 19, July 2026](https://www.st.com/resource/en/errata_sheet/es0182-stm32f405407xx-and-stm32f415417xx-device-errata-stmicroelectronics.pdf): TTCM unsupported, kept disabled; USB FIFO writes must not overlap other USB register accesses, USB IRQ is masked around main-context transmit; no dynamic ADC sequencer modifications; no other DMA2 peripheral clients or runtime APB changes; prefetch disabled conservatively for unknown silicon revision. This is a review of relevant modes, not a claim of exhaustive silicon qualification.
