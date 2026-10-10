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
| AIN1 | PA1 | 23 | ADC1_IN1 | Divider MCU_ADC, 0..VDDA only |
| AIN2 | PA2 | 24 | ADC1_IN2 | Same |
| AIN3 | PA3 | 25 | ADC1_IN3 | Same |
| AIN4 | PA4 | 29 | ADC1_IN4 | Same; DAC disabled |
| AIN5 | PA5 | 30 | ADC1_IN5 | Same; DAC disabled |
| AIN6 | PC0 | 15 | ADC1_IN10 | Same |
| AIN7 | PC1 | 16 | ADC1_IN11 | Same |
| AIN8 | PC2 | 17 | ADC1_IN12 | Same |
| AIN1 range | PD8 | 55 | GPIO OD, FT | R2 lower end, low=divided, released=R2 disconnected (biased input) |
| AIN2 range | PD9 | 56 | GPIO OD, FT | Same |
| AIN3 range | PD10 | 57 | GPIO OD, FT | Same |
| AIN4 range | PD11 | 58 | GPIO OD, FT | Same |
| AIN5 range | PD12 | 59 | GPIO OD, FT | Same |
| AIN6 range | PD13 | 60 | GPIO OD, FT | Same |
| AIN7 range | PD14 | 61 | GPIO OD, FT | Same |
| AIN8 range | PD15 | 62 | GPIO OD, FT | Same |
| SWD | PA13 / PA14 | 72 / 76 | SWDIO / SWCLK | Preserved; common GND, ST-Link power output disconnected when USB powers board |

PB8/PB12 are FT digital inputs in the selected AF, not analog inputs. STM32 internal pulls are disabled; DS8626 Table 48 note 5 requires this above VDD+0.3 V. Do not drive 5 V RXD into an unpowered MCU: the FT absolute input limit is VDD+4 V, so 5 V violates it at VDD=0. Power the MCU before the transceivers or isolate their RXD during power sequencing. Board/module grounds must be common on an unisolated bench. FT does not imply automotive surge tolerance.

NXP TJA1050 TXD thresholds are VIH >=2.0 V and VIL <=0.8 V, compatible with 3.3 V STM32 GPIO at the small TXD load. TJA1050 supply must be 4.75..5.25 V. Verify actual module part and pinout; do not substitute CANH/CANL for RXD/TXD. Verify its S input is strapped for the intended mode. Silent behavior here comes from bxCAN, not an assumed module S setting.

PD8..PD15 are FT open-drain, no pulls; writing zero sinks, writing one releases. The revised input has R1=100k to VREF, R3=47k from AIN and R2=10k to the range GPIO. Low enables R2, Hi-Z releases it; both modes have VREF bias. See `calibration.md` for nominal zero/gain. They overlap LCD signals; a fitted LCD would conflict. Low is preloaded before output enable at firmware startup. **During reset these pins are Hi-Z, so hardware does not guarantee a safe 0..15 V range.** Fixing this requires external hardware; firmware cannot remove that interval. Keep analog inputs disconnected until protection is verified. A nominal 3.3 V shunt diode does not guarantee ADC pin safety at actual current or during power loss; D1/D2 types and measurements are still required.

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

ADC1 clock=21 MHz (PCLK2/4), sample time initially 480 cycles plus 12 conversion cycles: about 23.43 us per channel, 187.43 us per eight-channel scan. TIM2 TRGO at exactly 1600 Hz (84 MHz / 52500). 16 scans produce one 10 ms window, 100 points/s/channel. Channels are scanned in table order, not simultaneously; timestamps identify the common window start/scan trigger, with channel offsets of approximately rank*23.43 us, not measured sample aperture. TIM5 is a 1 MHz 32-bit counter extended to 64 bits by its update ISR.

Revised R1=100k/R2=10k/R3=47k/C1=1nF network: approximate RC constants 7.6 us divided and 32 us released, excluding diode/ADC effects; see `calibration.md`. Sample time and `BOARD_SETTLING_US=20000` are provisional hardware parameters. Verify charge settling at the actual impedance, leakage, temperature and range transition. DMA2 Stream0/Channel0 buffers are in normal SRAM, never CCM.

## Termination and limitations

Each independent CAN segment needs its own topology and termination: normally 120 ohm at each physical end (approximately 60 ohm measured across an unpowered, fully connected segment). Check whether TJA1050 modules already contain 120 ohm and count those resistors. Do not add a terminator at every node. A bridge creates two segments; it does not electrically join them. The firmware provides no galvanic isolation.

Start CAN tests with internal silent loopback and no jumpers. A simple cross-connection TX->RX does not implement CAN bus feedback/ACK/arbitration. Never connect the two push-pull TX pins together. A logical bus emulator requires dominant-low combination fed back to both RX; it still cannot test physical CAN or two independent bridge segments.

## Primary sources and errata

- [DS8626 Rev 12, March 2026](https://www.st.com/resource/en/datasheet/stm32f407ve.pdf): Table 7 (FT and LQFP100 pins), Table 9 AF mapping, Tables 11/48/49 electrical limits.
- [RM0090](https://www.st.com/resource/en/reference_manual/dm00031020-stm32f405-407-415-417-437-455-469-application-note-stmicroelectronics.pdf): bxCAN, ADC/DMA, timers and USB.
- [TJA1050](https://www.nxp.com/docs/en/data-sheet/TJA1050.pdf): TXD thresholds and 5 V supply.
- [ES0182 Rev 19, July 2026](https://www.st.com/resource/en/errata_sheet/es0182-stm32f405407xx-and-stm32f415417xx-device-errata-stmicroelectronics.pdf): TTCM unsupported, kept disabled; USB FIFO writes must not overlap other USB register accesses, USB IRQ is masked around main-context transmit; no dynamic ADC sequencer modifications; no other DMA2 peripheral clients or runtime APB changes; prefetch disabled conservatively for unknown silicon revision. This is a review of relevant modes, not a claim of exhaustive silicon qualification.
