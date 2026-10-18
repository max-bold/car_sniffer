/* Bench build only. Both transceivers share CANH/CANL; bridge stays OFF.
 * Explicit LOOPBACK_TEST command sends 32 real frames, never internal loopback.
 * Each frame must have TXOK (physical ACK) and an exact peer RX match.
 */
static uint8_t physical_can_test(unsigned source) {
    unsigned peer=source^1u;
    uint8_t result=3;
    if(!engine.capture||!engine.confirmed[0]||!engine.confirmed[1]||engine.rate[0]!=engine.rate[1]) return 2;
    for(unsigned s=0;s<2;s++)abort_side(s,micros());
    if(can_config(0,engine.rate[0],1)||can_config(1,engine.rate[1],1)) goto cleanup;
    for(unsigned i=0;i<32;i++) {
        uint8_t data[8];for(unsigned j=0;j<8;j++)data[j]=(uint8_t)(i*17+j*31+source);
        unsigned extended=i&1u,remote=(i%8)==7,dlc=i%9;
        uint32_t id=extended?0x1230000u+i:0x500u+i;
        CAN_TxHeaderTypeDef h={.StdId=id,.ExtId=id,.IDE=extended?CAN_ID_EXT:CAN_ID_STD,
            .RTR=remote?CAN_RTR_REMOTE:CAN_RTR_DATA,.DLC=dlc};
        uint32_t mailbox;
        if(HAL_CAN_AddTxMessage(&can[source],&h,data,&mailbox)!=HAL_OK)goto cleanup;
        uint64_t deadline=micros()+100000;
        while(HAL_CAN_IsTxMessagePending(&can[source],mailbox)&&micros()<deadline) {}
        uint32_t tsr=can[source].Instance->TSR;
        uint32_t txok=mailbox==CAN_TX_MAILBOX0?CAN_TSR_TXOK0:mailbox==CAN_TX_MAILBOX1?CAN_TSR_TXOK1:CAN_TSR_TXOK2;
        if(!(tsr&txok))goto cleanup;
        while(rx_read[peer]==rx_written[peer]&&micros()<deadline) {}
        if(rx_read[peer]==rx_written[peer])goto cleanup;
        cs_can_t f=rx_queue[peer][rx_read[peer]%128];__DMB();rx_read[peer]++;
        if(f.id!=id||f.ide!=extended||f.rtr!=remote||f.dlc!=dlc||(!remote&&memcmp(f.data,data,dlc)))goto cleanup;
        if(rx_read[source]!=rx_written[source]||rx_read[peer]!=rx_written[peer]||rx_lost[0]||rx_lost[1])goto cleanup;
        engine_rx(&engine,&f);
        if((can[0].Instance->ESR&0xffff0077u)||(can[1].Instance->ESR&0xffff0077u))goto cleanup;
    }
    result=0;
cleanup:
    for(unsigned s=0;s<2;s++) {
        HAL_CAN_AbortTxRequest(&can[s],CAN_TX_MAILBOX0|CAN_TX_MAILBOX1|CAN_TX_MAILBOX2);
        if(can_config(s,engine.rate[s],0))result=3;
    }
    return result;
}
