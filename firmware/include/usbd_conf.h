#ifndef CS_USBD_CONF_H
#define CS_USBD_CONF_H
#include "stm32f4xx_hal.h"
#include <string.h>
#define USBD_MAX_NUM_INTERFACES 2U
#define USBD_MAX_NUM_CONFIGURATION 1U
#define USBD_MAX_STR_DESC_SIZ 256U
#define USBD_SELF_POWERED 0U
#define USBD_DEBUG_LEVEL 0U
#define USBD_LPM_ENABLED 0U
#define USBD_SUPPORT_USER_STRING_DESC 0U
void *usb_allocate(uint32_t size);
#define USBD_malloc usb_allocate
#define USBD_free(p) ((void)(p))
#define USBD_memset memset
#define USBD_memcpy memcpy
#define USBD_Delay HAL_Delay
#define USBD_UsrLog(...)
#define USBD_ErrLog(...)
#define USBD_DbgLog(...)
#endif
