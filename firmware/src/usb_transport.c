#include "usb_transport.h"
#include "board.h"
#include "usbd_core.h"
#include "usbd_cdc.h"
#include "usbd_ctlreq.h"
static USBD_HandleTypeDef device;
static PCD_HandleTypeDef pcd;
static uint8_t rx_packet[64], tx_packet[1040], rx_ring[2048];
static volatile uint16_t rx_w,rx_r;
static volatile uint32_t rx_loss;
static uint32_t class_memory[(sizeof(USBD_CDC_HandleTypeDef)+3)/4];
void *usb_allocate(uint32_t size) { return size<=sizeof(class_memory)?class_memory:NULL; }
static uint8_t dev_desc[18]={18,USB_DESC_TYPE_DEVICE,0,2,2,2,0,64,0x83,0x04,0x40,0x57,0,1,1,2,3,1};
static uint8_t lang_desc[4]={4,USB_DESC_TYPE_STRING,9,4}, string_desc[256];
static uint8_t *get_dev(USBD_SpeedTypeDef speed,uint16_t *n) { (void)speed; *n=18; return dev_desc; }
static uint8_t *get_lang(USBD_SpeedTypeDef speed,uint16_t *n) { (void)speed; *n=4; return lang_desc; }
static uint8_t *str(const char *s,uint16_t *n) { USBD_GetString((uint8_t *)s,string_desc,n); return string_desc; }
static uint8_t *get_mfr(USBD_SpeedTypeDef s,uint16_t *n) { (void)s; return str("Car Sniffer development",n); }
static uint8_t *get_product(USBD_SpeedTypeDef s,uint16_t *n) { (void)s; return str("Car Sniffer F407VE",n); }
static uint8_t *get_serial(USBD_SpeedTypeDef s,uint16_t *n) {
    (void)s; static char serial[25]; const char *hex="0123456789ABCDEF";
    for(unsigned i=0;i<12;i++) { uint8_t b=*(uint8_t *)(UID_BASE+i); serial[2*i]=hex[b>>4]; serial[2*i+1]=hex[b&15]; }
    return str(serial,n);
}
static uint8_t *get_config(USBD_SpeedTypeDef s,uint16_t *n) { (void)s; return str("CDC",n); }
static USBD_DescriptorsTypeDef descriptors={get_dev,get_lang,get_mfr,get_product,get_serial,get_config,get_config};
static int8_t cdc_init(void) { rx_r=rx_w=0; USBD_CDC_SetRxBuffer(&device,rx_packet); USBD_CDC_SetTxBuffer(&device,tx_packet,0); return USBD_OK; }
static int8_t cdc_deinit(void) { rx_r=rx_w=0; return USBD_OK; }
static int8_t cdc_control(uint8_t cmd,uint8_t *data,uint16_t length) {
    static uint8_t coding[7]={0,0xc2,1,0,0,0,8};
    if(cmd==CDC_SET_LINE_CODING&&length==7) memcpy(coding,data,7);
    if(cmd==CDC_GET_LINE_CODING&&length==7) memcpy(data,coding,7);
    return USBD_OK;
}
static int8_t cdc_rx(uint8_t *data,uint32_t *length) {
    for(unsigned i=0;i<*length;i++) {
        if((uint16_t)(rx_w-rx_r)>=sizeof(rx_ring)) rx_loss++;
        else { rx_ring[rx_w%sizeof(rx_ring)]=data[i]; __DMB(); rx_w++; }
    }
    USBD_CDC_SetRxBuffer(&device,rx_packet); USBD_CDC_ReceivePacket(&device); return USBD_OK;
}
static int8_t cdc_tx_done(uint8_t *p,uint32_t *n,uint8_t ep) { (void)p;(void)n;(void)ep;return USBD_OK; }
static USBD_CDC_ItfTypeDef cdc={cdc_init,cdc_deinit,cdc_control,cdc_rx,cdc_tx_done};
int usb_ready(void) { return device.dev_state==USBD_STATE_CONFIGURED&&device.pClassData!=NULL; }
int usb_tx_idle(void) { USBD_CDC_HandleTypeDef *h=device.pClassData;return usb_ready()&&h&&h->TxState==0; }
uint32_t usb_rx_losses(void) { return rx_loss; }
size_t usb_read(uint8_t *out,size_t max) {
    size_t n=0; while(n<max&&rx_r!=rx_w) { out[n++]=rx_ring[rx_r%sizeof(rx_ring)]; __DMB(); rx_r++; } return n;
}
int usb_send(const uint8_t *p,uint16_t n) {
    if(!usb_ready()||n>sizeof(tx_packet)) return 0;
    USBD_CDC_HandleTypeDef *h=device.pClassData;
    if(!h||h->TxState) return 0;
    memcpy(tx_packet,p,n);
    /* ES0182 2.14.1: main-context FIFO writes cannot overlap USB IRQ register accesses. */
    NVIC_DisableIRQ(OTG_FS_IRQn);
    USBD_CDC_SetTxBuffer(&device,tx_packet,n);int ok=USBD_CDC_TransmitPacket(&device)==USBD_OK;
    NVIC_EnableIRQ(OTG_FS_IRQn);return ok;
}
void usb_init(void) {
    /* Board has a permanent external DP pull-up. Force a disconnect across SWD resets. */
    GPIO_InitTypeDef g={.Pin=BOARD_USB_DP_PIN,.Mode=GPIO_MODE_OUTPUT_OD,.Pull=GPIO_NOPULL,.Speed=GPIO_SPEED_FREQ_LOW};
    HAL_GPIO_WritePin(BOARD_USB_PORT,BOARD_USB_DP_PIN,GPIO_PIN_RESET);HAL_GPIO_Init(BOARD_USB_PORT,&g);HAL_Delay(25);
    USBD_Init(&device,&descriptors,0); USBD_RegisterClass(&device,&USBD_CDC); USBD_CDC_RegisterInterface(&device,&cdc); USBD_Start(&device);
}
void OTG_FS_IRQHandler(void) { HAL_PCD_IRQHandler(&pcd); }
void HAL_PCD_MspInit(PCD_HandleTypeDef *h) {
    (void)h; __HAL_RCC_GPIOA_CLK_ENABLE();
    GPIO_InitTypeDef g={.Pin=BOARD_USB_PINS,.Mode=GPIO_MODE_AF_PP,.Pull=GPIO_NOPULL,.Speed=GPIO_SPEED_FREQ_VERY_HIGH,.Alternate=BOARD_USB_AF};
    HAL_GPIO_Init(BOARD_USB_PORT,&g); __HAL_RCC_USB_OTG_FS_CLK_ENABLE(); HAL_NVIC_SetPriority(OTG_FS_IRQn,6,0); HAL_NVIC_EnableIRQ(OTG_FS_IRQn);
}
void HAL_PCD_SetupStageCallback(PCD_HandleTypeDef *h) { USBD_LL_SetupStage(h->pData,(uint8_t *)h->Setup); }
void HAL_PCD_DataOutStageCallback(PCD_HandleTypeDef *h,uint8_t ep) { USBD_LL_DataOutStage(h->pData,ep,h->OUT_ep[ep].xfer_buff); }
void HAL_PCD_DataInStageCallback(PCD_HandleTypeDef *h,uint8_t ep) { USBD_LL_DataInStage(h->pData,ep,h->IN_ep[ep].xfer_buff); }
void HAL_PCD_SOFCallback(PCD_HandleTypeDef *h) { USBD_LL_SOF(h->pData); }
void HAL_PCD_ResetCallback(PCD_HandleTypeDef *h) { USBD_LL_SetSpeed(h->pData,USBD_SPEED_FULL); USBD_LL_Reset(h->pData); }
void HAL_PCD_SuspendCallback(PCD_HandleTypeDef *h) { USBD_LL_Suspend(h->pData); }
void HAL_PCD_ResumeCallback(PCD_HandleTypeDef *h) { USBD_LL_Resume(h->pData); }
void HAL_PCD_ISOOUTIncompleteCallback(PCD_HandleTypeDef *h,uint8_t ep) { USBD_LL_IsoOUTIncomplete(h->pData,ep); }
void HAL_PCD_ISOINIncompleteCallback(PCD_HandleTypeDef *h,uint8_t ep) { USBD_LL_IsoINIncomplete(h->pData,ep); }
void HAL_PCD_ConnectCallback(PCD_HandleTypeDef *h) { USBD_LL_DevConnected(h->pData); }
void HAL_PCD_DisconnectCallback(PCD_HandleTypeDef *h) { USBD_LL_DevDisconnected(h->pData); }
USBD_StatusTypeDef USBD_LL_Init(USBD_HandleTypeDef *d) {
    pcd.Instance=USB_OTG_FS; pcd.Init.dev_endpoints=4; pcd.Init.speed=PCD_SPEED_FULL;
    pcd.Init.phy_itface=PCD_PHY_EMBEDDED; pcd.Init.vbus_sensing_enable=DISABLE;
    pcd.pData=d; d->pData=&pcd;
    if(HAL_PCD_Init(&pcd)!=HAL_OK) return USBD_FAIL;
    HAL_PCDEx_SetRxFiFo(&pcd,128); HAL_PCDEx_SetTxFiFo(&pcd,0,64); HAL_PCDEx_SetTxFiFo(&pcd,1,112); HAL_PCDEx_SetTxFiFo(&pcd,2,16);
    return USBD_OK;
}
USBD_StatusTypeDef USBD_LL_DeInit(USBD_HandleTypeDef *d) { HAL_PCD_DeInit(d->pData);return USBD_OK; }
USBD_StatusTypeDef USBD_LL_Start(USBD_HandleTypeDef *d) { HAL_PCD_Start(d->pData);return USBD_OK; }
USBD_StatusTypeDef USBD_LL_Stop(USBD_HandleTypeDef *d) { HAL_PCD_Stop(d->pData);return USBD_OK; }
USBD_StatusTypeDef USBD_LL_OpenEP(USBD_HandleTypeDef *d,uint8_t a,uint8_t t,uint16_t m) { HAL_PCD_EP_Open(d->pData,a,m,t);return USBD_OK; }
USBD_StatusTypeDef USBD_LL_CloseEP(USBD_HandleTypeDef *d,uint8_t a) { HAL_PCD_EP_Close(d->pData,a);return USBD_OK; }
USBD_StatusTypeDef USBD_LL_FlushEP(USBD_HandleTypeDef *d,uint8_t a) { HAL_PCD_EP_Flush(d->pData,a);return USBD_OK; }
USBD_StatusTypeDef USBD_LL_StallEP(USBD_HandleTypeDef *d,uint8_t a) { HAL_PCD_EP_SetStall(d->pData,a);return USBD_OK; }
USBD_StatusTypeDef USBD_LL_ClearStallEP(USBD_HandleTypeDef *d,uint8_t a) { HAL_PCD_EP_ClrStall(d->pData,a);return USBD_OK; }
uint8_t USBD_LL_IsStallEP(USBD_HandleTypeDef *d,uint8_t a) { PCD_HandleTypeDef *h=d->pData;return a&128?h->IN_ep[a&127].is_stall:h->OUT_ep[a&127].is_stall; }
USBD_StatusTypeDef USBD_LL_SetUSBAddress(USBD_HandleTypeDef *d,uint8_t a) { HAL_PCD_SetAddress(d->pData,a);return USBD_OK; }
USBD_StatusTypeDef USBD_LL_Transmit(USBD_HandleTypeDef *d,uint8_t a,uint8_t *b,uint32_t n) { HAL_PCD_EP_Transmit(d->pData,a,b,n);return USBD_OK; }
USBD_StatusTypeDef USBD_LL_PrepareReceive(USBD_HandleTypeDef *d,uint8_t a,uint8_t *b,uint32_t n) { HAL_PCD_EP_Receive(d->pData,a,b,n);return USBD_OK; }
uint32_t USBD_LL_GetRxDataSize(USBD_HandleTypeDef *d,uint8_t a) { return HAL_PCD_EP_GetRxCount(d->pData,a); }
void USBD_LL_Delay(uint32_t n) { HAL_Delay(n); }
