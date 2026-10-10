#include "board.h"
#include "engine.h"
#include "calibration_flash.h"
#include "usb_transport.h"
#include <string.h>
#include <math.h>
static engine_t engine;
static const uint32_t board_adc_channels[8]=BOARD_ADC_CHANNELS;
static CAN_HandleTypeDef can[2];
static ADC_HandleTypeDef adc;
static DMA_HandleTypeDef dma;
static TIM_HandleTypeDef adc_timer,time_timer;
static volatile uint32_t time_high;
static uint32_t boot_id;
static uint16_t adc_dma[2][16][8] __attribute__((aligned(4)));
static uint16_t adc_copy[4][16][8];
static uint64_t adc_copy_t[4],adc_start;
static volatile uint32_t adc_written,adc_read,adc_lost;
static uint32_t scan_blocks;
static cs_can_t rx_queue[2][128];
static volatile uint16_t rx_written[2],rx_read[2];
static volatile uint32_t rx_lost[2];
static forward_t inflight[2];
static uint8_t tx_active[2],mode[2],recovery_count[2],was_busoff[2];
static uint64_t recover_at[2];
static uint32_t last_esr[2];
static uint8_t auto_index[2],auto_active[2],auto_valid[2];
static uint64_t auto_deadline[2];
static const uint32_t rates[]={125000,250000,500000,1000000,100000,83333};
static const uint16_t prescalers[]={24,12,6,3,30,36};
static uint8_t filters_ready;
static uint64_t raw_until;
static uint64_t analog_after[8];
static uint8_t raw_channel;
/* Fixed record queue, main-loop producer/consumer. Responses have a separate queue. */
typedef struct { uint8_t kind; uint16_t size; uint8_t data[128]; } telemetry_t;
static telemetry_t telemetry[256],responses[16];
static uint16_t telemetry_w,telemetry_r,response_w,response_r;
static uint32_t telemetry_lost,reported_lost,sequence;
static cs_parser_t parser;
static uint8_t packet[CS_MAX_PACKET];
uint64_t micros(void) {
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint32_t hi=time_high,lo=TIM5->CNT;
    if(TIM5->SR&TIM_SR_UIF) { hi++;lo=TIM5->CNT; }
    if(!mask) __enable_irq();
    return ((uint64_t)hi<<32)|lo;
}
static void fatal(void) { __disable_irq(); for(;;) {} }
static void check(HAL_StatusTypeDef s) { if(s!=HAL_OK) fatal(); }
void SysTick_Handler(void) { HAL_IncTick(); }
void TIM5_IRQHandler(void) { if(TIM5->SR&TIM_SR_UIF) { TIM5->SR=~TIM_SR_UIF; time_high++; } }
void DMA2_Stream0_IRQHandler(void) { HAL_DMA_IRQHandler(&dma); }
static void clock_init(void) {
    __HAL_RCC_PWR_CLK_ENABLE(); __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);
    RCC_OscInitTypeDef o={.OscillatorType=RCC_OSCILLATORTYPE_HSE,.HSEState=RCC_HSE_ON};
    o.PLL.PLLState=RCC_PLL_ON;o.PLL.PLLSource=RCC_PLLSOURCE_HSE;o.PLL.PLLM=8;o.PLL.PLLN=336;o.PLL.PLLP=RCC_PLLP_DIV2;o.PLL.PLLQ=7;
    check(HAL_RCC_OscConfig(&o));
    RCC_ClkInitTypeDef c={.ClockType=RCC_CLOCKTYPE_SYSCLK|RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2,.SYSCLKSource=RCC_SYSCLKSOURCE_PLLCLK,.AHBCLKDivider=RCC_SYSCLK_DIV1,.APB1CLKDivider=RCC_HCLK_DIV4,.APB2CLKDivider=RCC_HCLK_DIV2};
    check(HAL_RCC_ClockConfig(&c,FLASH_LATENCY_5));
}
static void io_init(void) {
    __HAL_RCC_GPIOA_CLK_ENABLE();__HAL_RCC_GPIOB_CLK_ENABLE();__HAL_RCC_GPIOC_CLK_ENABLE();__HAL_RCC_GPIOD_CLK_ENABLE();
    /* Preload low before enabling OD: no software-created unity-range pulse. Reset Hi-Z remains a hardware limitation. */
    HAL_GPIO_WritePin(BOARD_RANGE_PORT,BOARD_RANGE_PINS,GPIO_PIN_RESET);
    GPIO_InitTypeDef g={.Pin=BOARD_RANGE_PINS,.Mode=GPIO_MODE_OUTPUT_OD,.Pull=GPIO_NOPULL,.Speed=GPIO_SPEED_FREQ_LOW};
    HAL_GPIO_Init(BOARD_RANGE_PORT,&g);
    g.Pin=BOARD_ADC_PORT_A_PINS;g.Mode=GPIO_MODE_ANALOG;HAL_GPIO_Init(GPIOA,&g);
    g.Pin=BOARD_ADC_PORT_C_PINS;HAL_GPIO_Init(GPIOC,&g);
    g.Pin=BOARD_CAN_A_PINS|BOARD_CAN_B_PINS;g.Mode=GPIO_MODE_AF_PP;g.Alternate=BOARD_CAN_AF;g.Speed=GPIO_SPEED_FREQ_VERY_HIGH;g.Pull=GPIO_NOPULL;
    HAL_GPIO_Init(BOARD_CAN_PORT,&g);
}
static void time_init(void) {
    __HAL_RCC_TIM5_CLK_ENABLE();time_timer.Instance=TIM5;time_timer.Init.Prescaler=83;time_timer.Init.Period=0xffffffffu;
    check(HAL_TIM_Base_Init(&time_timer));__HAL_TIM_CLEAR_FLAG(&time_timer,TIM_FLAG_UPDATE);__HAL_TIM_SET_COUNTER(&time_timer,0);
    HAL_NVIC_SetPriority(TIM5_IRQn,0,0);HAL_NVIC_EnableIRQ(TIM5_IRQn);check(HAL_TIM_Base_Start_IT(&time_timer));
}
static void emit(uint8_t kind,const void *data,uint16_t n,void *ctx) {
    (void)ctx;
    telemetry_t *q=kind==CS_RESPONSE?responses:telemetry;
    uint16_t *w=kind==CS_RESPONSE?&response_w:&telemetry_w,*r=kind==CS_RESPONSE?&response_r:&telemetry_r;
    unsigned cap=kind==CS_RESPONSE?16:256;
    if(n>128||(uint16_t)(*w-*r)>=cap) { telemetry_lost++; return; }
    telemetry_t *v=&q[(*w)++%cap];v->kind=kind;v->size=n;memcpy(v->data,data,n);
}
static void flush_usb(void) {
    if(!usb_ready()) { telemetry_lost+=(uint16_t)(telemetry_w-telemetry_r);telemetry_r=telemetry_w;response_r=response_w;return; }
    if(!usb_tx_idle()) return;
    telemetry_t *q=response_w!=response_r?responses:telemetry;
    uint16_t *r=q==responses?&response_r:&telemetry_r,w=q==responses?response_w:telemetry_w;
    unsigned cap=q==responses?16:256;
    if(*r==w) return;
    uint8_t payload[CS_MAX_PAYLOAD],kind=q[*r%cap].kind;uint16_t n=0,count=0;
    while((uint16_t)(*r+count)!=w) {
        telemetry_t *v=&q[(uint16_t)(*r+count)%cap];
        if(v->kind!=kind||n+v->size>CS_MAX_PAYLOAD||(q==responses&&count)) break;
        memcpy(payload+n,v->data,v->size);n+=v->size;count++;
    }
    unsigned len=(unsigned)cs_encode(packet,kind,sequence,payload,n);
    if(usb_send(packet,(uint16_t)len)) { *r=(uint16_t)(*r+count);sequence++; }
}
static int can_config(unsigned s,uint32_t rate,uint8_t new_mode) {
    unsigned idx=0;while(idx<6&&rates[idx]!=rate) idx++;if(idx==6||s>1||new_mode>2) return -1;
    uint16_t hardware_discarded=0;
    IRQn_Type irq=s?CAN2_RX0_IRQn:CAN1_RX0_IRQn;
    HAL_NVIC_DisableIRQ(irq);
    if(can[s].Instance) {
        HAL_CAN_DeactivateNotification(&can[s],CAN_IT_RX_FIFO0_MSG_PENDING);HAL_CAN_Stop(&can[s]);
        CAN_RxHeaderTypeDef old_header;uint8_t old_data[8];
        while(HAL_CAN_GetRxFifoFillLevel(&can[s],CAN_RX_FIFO0)) {
            if(HAL_CAN_GetRxMessage(&can[s],CAN_RX_FIFO0,&old_header,old_data)!=HAL_OK) break;
            hardware_discarded++;
        }
        can[s].Instance->TSR=CAN_TSR_RQCP0|CAN_TSR_RQCP1|CAN_TSR_RQCP2;
    }
    /* Enter/leave init mode instead of resetting the shared CAN1 filter master. */
    /* A candidate cannot be confirmed by frames buffered at the previous bitrate. */
    __disable_irq();uint16_t discarded=(uint16_t)(rx_written[s]-rx_read[s]);rx_read[s]=rx_written[s];__enable_irq();
    discarded=(uint16_t)(discarded+hardware_discarded);
    if(discarded) { engine.counter[s][3]+=discarded;engine_event(&engine,s,EV_RECONFIG_DROP,discarded,micros()); }
    __HAL_RCC_CAN1_CLK_ENABLE();__HAL_RCC_CAN2_CLK_ENABLE();
    can[s].Instance=s?CAN2:CAN1;
    can[s].Init=(CAN_InitTypeDef){.Prescaler=prescalers[idx],.Mode=new_mode==0?CAN_MODE_SILENT:new_mode==1?CAN_MODE_NORMAL:CAN_MODE_SILENT_LOOPBACK,.SyncJumpWidth=CAN_SJW_1TQ,.TimeSeg1=CAN_BS1_11TQ,.TimeSeg2=CAN_BS2_2TQ,.AutoBusOff=DISABLE,.AutoWakeUp=DISABLE,.AutoRetransmission=DISABLE,.ReceiveFifoLocked=DISABLE,.TransmitFifoPriority=ENABLE};
    if(HAL_CAN_Init(&can[s])!=HAL_OK) return -1;
    CAN_FilterTypeDef f={.FilterBank=s?14:0,.FilterMode=CAN_FILTERMODE_IDMASK,.FilterScale=CAN_FILTERSCALE_32BIT,.FilterFIFOAssignment=CAN_RX_FIFO0,.FilterActivation=ENABLE,.SlaveStartFilterBank=14};
    if(!(filters_ready&(1u<<s))) { if(HAL_CAN_ConfigFilter(&can[s],&f)!=HAL_OK) return -1;filters_ready|=(1u<<s); }
    if(HAL_CAN_Start(&can[s])!=HAL_OK) return -1;
    HAL_CAN_ActivateNotification(&can[s],CAN_IT_RX_FIFO0_MSG_PENDING);
    HAL_NVIC_SetPriority(irq,2,0);HAL_NVIC_ClearPendingIRQ(irq);HAL_NVIC_EnableIRQ(irq);
    engine.rate[s]=rate;mode[s]=new_mode;last_esr[s]=0;tx_active[s]=0;return 0;
}
void CAN1_RX0_IRQHandler(void) { HAL_CAN_IRQHandler(&can[0]); }
void CAN2_RX0_IRQHandler(void) { HAL_CAN_IRQHandler(&can[1]); }
void HAL_CAN_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *h) {
    unsigned s=h->Instance==CAN2;CAN_RxHeaderTypeDef head;uint8_t data[8];
    /* Hardware FIFO depth is three; drain only that bounded amount. */
    for(unsigned n=0;n<3&&HAL_CAN_GetRxFifoFillLevel(h,CAN_RX_FIFO0);n++) {
        if(HAL_CAN_GetRxMessage(h,CAN_RX_FIFO0,&head,data)!=HAL_OK) break;
        if((uint16_t)(rx_written[s]-rx_read[s])>=128) { rx_lost[s]++;continue; }
        cs_can_t f={.t=micros(),.id=head.IDE?head.ExtId:head.StdId,.side=(uint8_t)s,.ide=(uint8_t)!!head.IDE,.rtr=(uint8_t)!!head.RTR,.dlc=(uint8_t)head.DLC,.crc_ok=1};
        if(!f.rtr) memcpy(f.data,data,8);
        rx_queue[s][rx_written[s]%128]=f;__DMB();rx_written[s]++;
    }
}
static void adc_block(unsigned half) {
    uint32_t block=scan_blocks++;
    if(adc_written-adc_read>=4) { adc_lost++;return; }
    unsigned slot=adc_written%4;memcpy(adc_copy[slot],adc_dma[half],sizeof(adc_dma[half]));
    adc_copy_t[slot]=adc_start+(uint64_t)block*10000;__DMB();adc_written++;
}
void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *h) { (void)h;adc_block(0); }
void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *h) { (void)h;adc_block(1); }
void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *h) { (void)h;adc_lost++; }
static void adc_init(void) {
    __HAL_RCC_DMA2_CLK_ENABLE();__HAL_RCC_ADC1_CLK_ENABLE();__HAL_RCC_TIM2_CLK_ENABLE();
    dma.Instance=DMA2_Stream0;dma.Init=(DMA_InitTypeDef){.Channel=DMA_CHANNEL_0,.Direction=DMA_PERIPH_TO_MEMORY,.PeriphInc=DMA_PINC_DISABLE,.MemInc=DMA_MINC_ENABLE,.PeriphDataAlignment=DMA_PDATAALIGN_HALFWORD,.MemDataAlignment=DMA_MDATAALIGN_HALFWORD,.Mode=DMA_CIRCULAR,.Priority=DMA_PRIORITY_HIGH,.FIFOMode=DMA_FIFOMODE_DISABLE};
    check(HAL_DMA_Init(&dma));__HAL_LINKDMA(&adc,DMA_Handle,dma);
    HAL_NVIC_SetPriority(DMA2_Stream0_IRQn,3,0);HAL_NVIC_EnableIRQ(DMA2_Stream0_IRQn);
    adc.Instance=ADC1;adc.Init=(ADC_InitTypeDef){.ClockPrescaler=ADC_CLOCK_SYNC_PCLK_DIV4,.Resolution=ADC_RESOLUTION_12B,.ScanConvMode=ENABLE,.ContinuousConvMode=DISABLE,.DiscontinuousConvMode=DISABLE,.ExternalTrigConvEdge=ADC_EXTERNALTRIGCONVEDGE_RISING,.ExternalTrigConv=ADC_EXTERNALTRIGCONV_T2_TRGO,.DataAlign=ADC_DATAALIGN_RIGHT,.NbrOfConversion=8,.DMAContinuousRequests=ENABLE,.EOCSelection=ADC_EOC_SEQ_CONV};
    check(HAL_ADC_Init(&adc));
    for(unsigned i=0;i<8;i++) { ADC_ChannelConfTypeDef c={.Channel=board_adc_channels[i],.Rank=i+1,.SamplingTime=BOARD_ADC_SAMPLE};check(HAL_ADC_ConfigChannel(&adc,&c)); }
    adc_timer.Instance=TIM2;adc_timer.Init.Prescaler=0;adc_timer.Init.Period=84000000/BOARD_ADC_SCAN_HZ-1;check(HAL_TIM_Base_Init(&adc_timer));
    TIM_MasterConfigTypeDef m={.MasterOutputTrigger=TIM_TRGO_UPDATE,.MasterSlaveMode=TIM_MASTERSLAVEMODE_DISABLE};check(HAL_TIMEx_MasterConfigSynchronization(&adc_timer,&m));
    check(HAL_ADC_Start_DMA(&adc,(uint32_t *)adc_dma,256));adc_start=micros()+625;check(HAL_TIM_Base_Start(&adc_timer));
}
static void abort_side(unsigned s,uint64_t now) {
    if(tx_active[s]) { HAL_CAN_AbortTxRequest(&can[s],CAN_TX_MAILBOX0);engine_tx(&engine,&inflight[s].frame,s,TX_DROPPED,-1,now);tx_active[s]=0; }
    engine_drop(&engine,s,now);
}
static void bridge_off(uint64_t now) {
    engine_bridge(&engine,0,now);
    for(unsigned s=0;s<2;s++) { abort_side(s,now);can_config(s,engine.rate[s],0); }
}
static void send_status(uint64_t now) {
    cs_status_t st={.t=now,.boot=boot_id,.flags=telemetry_lost,.generation=engine.generation,.bridge=engine.bridge,.capture=engine.capture};
    memcpy(st.uid,(void *)UID_BASE,12);
    for(unsigned s=0;s<2;s++)st.mode[s]=mode[s]|((can[s].Instance->ESR&7)<<4);
    memcpy(st.rate,engine.rate,sizeof(st.rate));memcpy(st.counters,engine.counter,sizeof(st.counters));emit(CS_STATUS,&st,sizeof(st),NULL);
}
static void command(uint8_t kind,uint32_t seq,const uint8_t *p,uint16_t n,void *ctx) {
    (void)seq;(void)ctx;if(kind!=CS_COMMAND||n<5) return;
    uint32_t request=cs_u32(p);uint8_t cmd=p[4],result=0;const uint8_t *a=p+5;unsigned len=n-5;uint64_t now=micros();
    switch(cmd) {
    case CMD_STATUS: if(len) result=1;else send_status(now);break;
    case CMD_CAN_CONFIG:
        if(len!=5||a[0]>1) { result=1;break; }
        if(engine.bridge) bridge_off(now);
        { unsigned s=a[0];uint32_t rate=cs_u32(a+1);abort_side(s,now);auto_active[s]=0;recovery_count[s]=0;was_busoff[s]=0;
          if(!rate) { auto_active[s]=1;auto_index[s]=0;auto_valid[s]=0;engine.confirmed[s]=0;can_config(s,rates[0],0);auto_deadline[s]=now+300000;cs_auto_t v={now,(uint8_t)s,0,rates[0]};emit(CS_AUTO,&v,sizeof(v),NULL); }
          else { result=can_config(s,rate,0)?1:0;engine.confirmed[s]=(uint8_t)!result; } }
        break;
    case CMD_BRIDGE:
        if(len!=1||a[0]>1) result=1;
        else if(!a[0]) bridge_off(now);
        else if(auto_active[0]||auto_active[1]||engine_bridge(&engine,1,now)) result=2;
        else { for(unsigned s=0;s<2;s++) if(can_config(s,engine.rate[s],1)) result=3;if(result) bridge_off(now); }
        break;
    case CMD_CAPTURE:
        if(len!=1||a[0]>1) result=1;
        else { engine_capture(&engine,a[0],now);for(unsigned c=0;c<8;c++)analog_after[c]=now; }
        break;
    case CMD_CHANNEL:
        if(len!=3||a[0]>=8||a[1]>1||a[2]>1) result=1;
        else { unsigned c=a[0];engine.enabled[c]=a[1];if(engine.range[c]!=a[2]) { board_range(c,a[2]);engine_range(&engine,c,a[2],now,BOARD_SETTLING_US);analog_after[c]=now; } }
        break;
    case CMD_PROFILE:
        if(len<7||a[0]>=8||a[1]>1||a[6]>32||len!=7u+a[6]*6u) { result=1;break; }
        { cal_profile_t profile={.version=cs_u32(a+2),.count=a[6]};for(unsigned i=0;i<profile.count;i++) { profile.points[i].raw=cs_u16(a+7+i*6);memcpy(&profile.points[i].volts,a+9+i*6,4); }
          result=engine_profile(&engine,a[0],a[1],&profile)?1:0;
          if(!result) { analog_after[a[0]]=now;memset(&engine.windows[a[0]],0,sizeof(engine.windows[a[0]])); } }
        break;
    case CMD_LINEAR_PROFILE:
        if(len!=14||a[0]>=8||a[1]>1) { result=1;break; }
        { cal_profile_t profile={.version=cs_u32(a+2),.linear=1};
          memcpy(&profile.zero,a+6,4);memcpy(&profile.gain,a+10,4);
          result=engine_profile(&engine,a[0],a[1],&profile)?1:0;
          if(!result) { analog_after[a[0]]=now;memset(&engine.windows[a[0]],0,sizeof(engine.windows[a[0]])); } }
        break;
    case CMD_SAVE_CALIBRATION:
        if(len||engine.capture||engine.bridge) result=2;
        else result=calibration_save(&engine)?1:0;
        break;
    case CMD_RELOAD_CALIBRATION:
        if(len||engine.capture||engine.bridge) result=2;
        else { calibration_load(&engine);memset(engine.windows,0,sizeof(engine.windows)); }
        break;
    case CMD_READ_COEFFICIENTS:
        if(len) { result=1;break; }
        { cs_coefficients_t values[16];
          for(unsigned c=0;c<8;c++)for(unsigned r=0;r<2;r++) {
              cs_coefficients_t *v=&values[c*2+r];v->request=request;engine_coefficients(&engine,c,r,v);emit(CS_COEFFICIENTS,v,sizeof(*v),NULL);
          }
          }
        break;
    case CMD_RAW:
        if(len!=3||a[0]>=8||cs_u16(a+1)>10000) result=1;
        else { raw_channel=a[0];raw_until=now+(uint64_t)cs_u16(a+1)*1000; }break;
    case CMD_CLEAR_COUNTERS:
        if(len) result=1;else memset(engine.counter,0,sizeof(engine.counter));break;
    case CMD_LOOPBACK:
        if(len!=1||a[0]>1||engine.bridge||auto_active[0]||auto_active[1]) { result=2;break; }
        { unsigned s=a[0];abort_side(s,now);can_config(s,engine.rate[s],2);CAN_TxHeaderTypeDef h={.StdId=0x321,.IDE=CAN_ID_STD,.RTR=CAN_RTR_DATA,.DLC=8};uint8_t data[8]={0x43,0x53,1,2,3,4,5,6};uint32_t mailbox;result=HAL_CAN_AddTxMessage(&can[s],&h,data,&mailbox)!=HAL_OK;engine_event(&engine,s,EV_LOOPBACK,0,now); }break;
    default:result=1;
    }
    uint8_t reply[14];memcpy(reply,&request,4);reply[4]=cmd;reply[5]=result;memcpy(reply+6,&now,8);emit(CS_RESPONSE,reply,sizeof(reply),NULL);
}
static void can_poll(unsigned s,uint64_t now) {
    uint32_t esr=can[s].Instance->ESR,lec=(esr>>4)&7;
    engine.counter[s][6]=(esr>>16)&255;engine.counter[s][7]=(esr>>24)&255;
    if(lec&&lec!=7) { engine.counter[s][2]++;engine_event(&engine,s,EV_LEC,lec,now);MODIFY_REG(can[s].Instance->ESR,CAN_ESR_LEC,CAN_ESR_LEC); }
    if((esr&7)!=(last_esr[s]&7)) engine_event(&engine,s,EV_STATE,esr&7,now);
    last_esr[s]=esr;
    if(can[s].Instance->RF0R&CAN_RF0R_FOVR0) { can[s].Instance->RF0R=CAN_RF0R_FOVR0;rx_lost[s]++; }
    if(rx_lost[s]) { uint32_t mask=__get_PRIMASK();__disable_irq();uint32_t lost=rx_lost[s];rx_lost[s]=0;if(!mask)__enable_irq();engine.counter[s][3]+=lost;engine_event(&engine,s,EV_RX_OVERFLOW,lost,now); }
    if(esr&CAN_ESR_BOFF) {
        if(!was_busoff[s]) { was_busoff[s]=1;recover_at[s]=now+1000000;abort_side(s,now); }
        if(now>=recover_at[s]&&recovery_count[s]<3) {
            recovery_count[s]++;recover_at[s]=now+1000000;engine_event(&engine,s,EV_RECOVERY,recovery_count[s],now);
            can_config(s,engine.rate[s],engine.bridge?1:0);
        }
        return;
    }
    if(was_busoff[s]) { was_busoff[s]=0;engine_event(&engine,s,EV_RECOVERY,0,now); }
    if(tx_active[s]) {
        uint32_t tsr=can[s].Instance->TSR;
        if(tsr&CAN_TSR_RQCP0) { engine_tx(&engine,&inflight[s].frame,s,(tsr&CAN_TSR_TXOK0)?TX_SENT:TX_FAILED,(tsr&CAN_TSR_TXOK0)?1:-1,now);can[s].Instance->TSR=CAN_TSR_RQCP0;tx_active[s]=0; }
        else if(now>=inflight[s].deadline) { HAL_CAN_AbortTxRequest(&can[s],CAN_TX_MAILBOX0);engine_tx(&engine,&inflight[s].frame,s,TX_EXPIRED,-1,now);engine_event(&engine,s,EV_EXPIRED,inflight[s].frame.frame_id,now);tx_active[s]=0; }
    }
    if(engine.bridge&&!tx_active[s]&&HAL_CAN_GetTxMailboxesFreeLevel(&can[s])==3&&engine_take(&engine,s,now,&inflight[s])) {
        cs_can_t *f=&inflight[s].frame;CAN_TxHeaderTypeDef h={.StdId=f->id,.ExtId=f->id,.IDE=f->ide?CAN_ID_EXT:CAN_ID_STD,.RTR=f->rtr?CAN_RTR_REMOTE:CAN_RTR_DATA,.DLC=f->dlc};uint32_t mailbox;
        if(HAL_CAN_AddTxMessage(&can[s],&h,f->data,&mailbox)==HAL_OK) tx_active[s]=1;
        else engine_tx(&engine,f,s,TX_FAILED,-1,now);
    }
}
static void auto_poll(unsigned s,uint64_t now) {
    if(!auto_active[s]) return;
    if(auto_valid[s]>=3) { engine.confirmed[s]=1;auto_active[s]=0;cs_auto_t v={now,(uint8_t)s,1,engine.rate[s]};emit(CS_AUTO,&v,sizeof(v),NULL);return; }
    if(now<auto_deadline[s]) return;
    auto_valid[s]=0;
    if(++auto_index[s]>=6) { auto_active[s]=0;engine.confirmed[s]=0;cs_auto_t v={now,(uint8_t)s,2,0};emit(CS_AUTO,&v,sizeof(v),NULL); }
    else { can_config(s,rates[auto_index[s]],0);auto_deadline[s]=now+300000;cs_auto_t v={now,(uint8_t)s,0,engine.rate[s]};emit(CS_AUTO,&v,sizeof(v),NULL); }
}
int main(void) {
    HAL_Init();clock_init();io_init();time_init();engine_init(&engine,emit,NULL);calibration_load(&engine);
    __HAL_RCC_RNG_CLK_ENABLE();RNG_HandleTypeDef rng={.Instance=RNG};check(HAL_RNG_Init(&rng));check(HAL_RNG_GenerateRandomNumber(&rng,&boot_id));HAL_RNG_DeInit(&rng);
    can_config(0,500000,0);can_config(1,500000,0);adc_init();usb_init();uint64_t status_at=0;
    for(unsigned c=0;c<8;c++)engine.settle_until[c]=micros()+BOARD_SETTLING_US;
    uint8_t previous_usb_ready=0;uint32_t reported_rx_loss=0;
    for(;;) {
        uint64_t now=micros();
        for(unsigned s=0;s<2;s++) {
            can_poll(s,now);
            for(unsigned budget=0;budget<16&&rx_read[s]!=rx_written[s];budget++) {
                cs_can_t f=rx_queue[s][rx_read[s]%128];__DMB();rx_read[s]++;
                if(auto_active[s]&&auto_valid[s]<255) auto_valid[s]++;
                engine_rx(&engine,&f);
                if(mode[s]==2) { engine_event(&engine,s,EV_LOOPBACK,1,f.t);can_config(s,engine.rate[s],0); }
            }
            auto_poll(s,now);
        }
        if(adc_lost) { __disable_irq();uint32_t lost=adc_lost;adc_lost=0;__enable_irq();engine_event(&engine,255,EV_DMA_LOSS,lost,now);memset(engine.windows,0,sizeof(engine.windows)); }
        if(adc_read!=adc_written) {
            unsigned slot=adc_read%4;
            for(unsigned i=0;i<16;i++) {
                uint64_t t=adc_copy_t[slot]+625*i;
                /* No pre-command sample may be interpreted with a new range/profile. */
                uint8_t enable[8];memcpy(enable,engine.enabled,8);
                for(unsigned c=0;c<8;c++)if(t<analog_after[c])engine.enabled[c]=0;
                engine_analog(&engine,adc_copy[slot][i],t);memcpy(engine.enabled,enable,8);
                for(unsigned c=0;c<8;c++)if(t<analog_after[c])memset(&engine.windows[c],0,sizeof(engine.windows[c]));
                if(t<raw_until&&t>=analog_after[raw_channel]) { cs_raw_t v={t,raw_channel,engine.range[raw_channel],adc_copy[slot][i][raw_channel]};emit(CS_RAW,&v,sizeof(v),NULL); }
            }
            __DMB();adc_read++;
        }
        uint8_t ready=(uint8_t)usb_ready();
        if(ready!=previous_usb_ready) { memset(&parser,0,sizeof(parser));previous_usb_ready=ready; }
        uint8_t input[128];size_t n=usb_read(input,sizeof(input));if(n) cs_feed(&parser,input,n,command,NULL);
        if(usb_rx_losses()!=reported_rx_loss) { uint32_t loss=usb_rx_losses();engine_event(&engine,255,EV_USB_LOSS,loss-reported_rx_loss,now);reported_rx_loss=loss; }
        if(now>=status_at) { status_at=now+500000;if(reported_lost!=telemetry_lost) { engine_event(&engine,255,EV_USB_LOSS,telemetry_lost-reported_lost,now);reported_lost=telemetry_lost; }send_status(now); }
        flush_usb();
    }
}
