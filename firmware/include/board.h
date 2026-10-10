#ifndef CS_BOARD_H
#define CS_BOARD_H
#include "stm32f4xx_hal.h"
/* Board schematic Y2=8 MHz. Keep all external wiring choices here. */
#define BOARD_CAN_PORT GPIOB
#define BOARD_CAN_A_PINS (GPIO_PIN_8|GPIO_PIN_9)
#define BOARD_CAN_B_PINS (GPIO_PIN_12|GPIO_PIN_13)
#define BOARD_CAN_AF GPIO_AF9_CAN1
#define BOARD_USB_PORT GPIOA
#define BOARD_USB_DP_PIN GPIO_PIN_12
#define BOARD_USB_PINS (GPIO_PIN_11|GPIO_PIN_12)
#define BOARD_USB_AF GPIO_AF10_OTG_FS
#define BOARD_RANGE_PORT GPIOD
#define BOARD_RANGE_FIRST_PIN 8u
#define BOARD_RANGE_PINS (0xffu<<BOARD_RANGE_FIRST_PIN)
#define BOARD_RANGE_LOW_IS_HIGH_RANGE 1
#define BOARD_SETTLING_US 20000u /* provisional; verify with actual divider */
#define BOARD_ADC_SAMPLE ADC_SAMPLETIME_480CYCLES
#define BOARD_ADC_SCAN_HZ 1600u
#define BOARD_ADC_PORT_A_PINS (GPIO_PIN_1|GPIO_PIN_2|GPIO_PIN_3|GPIO_PIN_4|GPIO_PIN_5)
#define BOARD_ADC_PORT_C_PINS (GPIO_PIN_0|GPIO_PIN_1|GPIO_PIN_2)
#define BOARD_ADC_CHANNELS {ADC_CHANNEL_1,ADC_CHANNEL_2,ADC_CHANNEL_3,ADC_CHANNEL_4,ADC_CHANNEL_5,ADC_CHANNEL_10,ADC_CHANNEL_11,ADC_CHANNEL_12}
/* Eight OD control lines PD8..PD15 overlap LCD data; LCD must be absent. */
static inline void board_range(unsigned channel,unsigned high_range) {
    int low=(high_range==BOARD_RANGE_LOW_IS_HIGH_RANGE);
    HAL_GPIO_WritePin(BOARD_RANGE_PORT,(uint16_t)(1u<<(BOARD_RANGE_FIRST_PIN+channel)),low?GPIO_PIN_RESET:GPIO_PIN_SET);
}
#endif
