#ifndef CS_USB_H
#define CS_USB_H
#include <stdint.h>
#include <stddef.h>
void usb_init(void);
int usb_send(const uint8_t *data,uint16_t size);
size_t usb_read(uint8_t *data,size_t capacity);
int usb_ready(void);
int usb_tx_idle(void);
uint32_t usb_rx_losses(void);
#endif
