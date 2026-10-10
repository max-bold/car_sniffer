#include "engine.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
static unsigned seen[10],packet_count;
static cs_adc_t analog;
static cs_tx_t tx;
static void emit(uint8_t kind,const void *p,uint16_t n,void *ctx) {
    (void)n;(void)ctx;seen[kind]++;
    if(kind==CS_ADC)memcpy(&analog,p,sizeof(analog));
    if(kind==CS_TX_STATUS)memcpy(&tx,p,sizeof(tx));
}
static void packet(uint8_t kind,uint32_t sequence,const uint8_t *p,uint16_t n,void *ctx) {
    (void)ctx;assert(kind==CS_STATUS);assert(sequence==(packet_count?0:0xffffffffu));assert(n==3&&!memcmp(p,"abc",3));packet_count++;
}
int main(void) {
    assert(sizeof(cs_can_t)==29&&sizeof(cs_adc_t)==28&&sizeof(cs_status_t)==108);
    assert(cs_crc32((const uint8_t *)"123456789",9)==0xcbf43926u);
    uint8_t b[100];size_t n=cs_encode(b,CS_STATUS,0xffffffffu,"abc",3);cs_parser_t parser={0};
    for(unsigned i=0;i<n;i++)cs_feed(&parser,b+i,1,packet,NULL);
    n=cs_encode(b,CS_STATUS,0,"abc",3);cs_feed(&parser,b,n,packet,NULL);assert(packet_count==2&&!parser.gaps);
    b[n-1]^=1;cs_feed(&parser,b,n,packet,NULL);assert(parser.bad_crc==1);
    engine_t e;engine_init(&e,emit,NULL);assert(engine_bridge(&e,1,0));
    e.rate[0]=e.rate[1]=500000;e.confirmed[0]=e.confirmed[1]=1;assert(!engine_bridge(&e,1,0));engine_capture(&e,1,0);
    for(unsigned s=0;s<2;s++) for(unsigned ide=0;ide<2;ide++) for(unsigned rtr=0;rtr<2;rtr++) {
        cs_can_t f={.t=100,.id=ide?0x18daf100:0x100,.side=s,.ide=ide,.rtr=rtr,.dlc=8,.data={1,2,3,4,5,6,7,8}};
        engine_rx(&e,&f);forward_t out;assert(engine_take(&e,s^1,101,&out));
        assert(!memcmp(&f,&out.frame,sizeof(f)));engine_tx(&e,&out.frame,s^1,TX_SENT,1,110);assert(tx.state==TX_SENT&&tx.ack==1);
    }
    /* Identical RX from both sides must remain separate. */
    cs_can_t a={.t=200,.id=0x123,.dlc=0,.side=0},bframe=a;bframe.side=1;
    engine_rx(&e,&a);engine_rx(&e,&bframe);assert(a.frame_id!=bframe.frame_id);
    forward_t out;assert(engine_take(&e,1,201,&out));assert(engine_take(&e,0,201,&out));
    engine_capture(&e,0,300);engine_rx(&e,&a);assert(engine_take(&e,1,301,&out));assert(e.bridge);
    engine_capture(&e,1,400);unsigned previous_rx=seen[CS_CAN_RX];engine_rx(&e,&a);assert(seen[CS_CAN_RX]==previous_rx);
    assert(engine_take(&e,1,401,&out));engine_capture(&e,0,402);
    /* No USB context is consulted by forwarding; full queue expires and bounds memory. */
    for(unsigned i=0;i<BRIDGE_QUEUE+5;i++)engine_rx(&e,&a);
    assert(e.counter[1][4]==5);assert(!engine_take(&e,1,100000,&out));assert(e.counter[1][5]==BRIDGE_QUEUE);
    engine_bridge(&e,0,100001);engine_rx(&e,&a);assert(!engine_take(&e,1,100002,&out));
    cal_profile_t profile={.version=3,.count=3,.points={{0,0},{1000,1},{2000,3}}};assert(!engine_profile(&e,0,0,&profile));
    engine_range(&e,0,0,0,0);for(unsigned c=1;c<8;c++)e.enabled[c]=0;engine_capture(&e,1,0);
    for(unsigned i=0;i<16;i++) { uint16_t raw[8]={i&1?1500:500};engine_analog(&e,raw,i*625); }
    assert(analog.t==0&&fabsf(analog.volts-1.25f)<.0001f&&analog.raw_mean==1000.f&&analog.version==3);
    engine_range(&e,0,1,10000,20000);
    for(unsigned i=0;i<16;i++) { uint16_t raw[8]={i?1000:4095};engine_analog(&e,raw,10000+i*625); }
    assert((analog.quality&(Q_CLIP|Q_SETTLE))==(Q_CLIP|Q_SETTLE)&&isnan(analog.volts));
    puts("C core: parser, bidirectional bridge, RTR/IDE, duplicate RX, stop/disconnect independence, queue overflow/expiry, nonlinear ADC and settling OK");return 0;
}
