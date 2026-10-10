#include "engine.h"
#include <string.h>
#include <math.h>
void engine_init(engine_t *e,emit_fn fn,void *ctx) {
    memset(e,0,sizeof(*e)); e->emit=fn; e->context=ctx;
    for(unsigned c=0;c<8;c++) { e->range[c]=1; e->enabled[c]=1; }
}
void engine_event(engine_t *e,unsigned side,unsigned code,uint32_t detail,uint64_t now) {
    cs_event_t v={.t=now,.side=(uint8_t)side,.code=(uint8_t)code,.detail=detail};
    if(side<2) { v.tec=e->counter[side][6]; v.rec=e->counter[side][7]; }
    e->emit(CS_EVENT,&v,sizeof(v),e->context);
}
void engine_tx(engine_t *e,const cs_can_t *f,unsigned dst,uint8_t state,int8_t ack,uint64_t now) {
    if(state==TX_SENT) e->counter[dst][1]++;
    if(state==TX_DROPPED||state==TX_FAILED) e->counter[dst][4]++;
    if(state==TX_EXPIRED) e->counter[dst][5]++;
    if(e->capture&&f->t>=e->capture_since) { cs_tx_t v={now,f->frame_id,(uint8_t)dst,state,ack}; e->emit(CS_TX_STATUS,&v,sizeof(v),e->context); }
}
void engine_drop(engine_t *e,unsigned dst,uint64_t now) {
    forward_queue_t *q=&e->queues[dst];
    while(q->read!=q->write) { forward_t *f=&q->items[q->read++%BRIDGE_QUEUE]; engine_tx(e,&f->frame,dst,TX_DROPPED,-1,now); }
}
int engine_bridge(engine_t *e,int enable,uint64_t now) {
    if(enable&&(!e->confirmed[0]||!e->confirmed[1]||e->rate[0]!=e->rate[1])) return -1;
    e->bridge=(uint8_t)!!enable;
    if(!enable) { engine_drop(e,0,now); engine_drop(e,1,now); engine_event(e,255,EV_BRIDGE_STOP,0,now); }
    return 0;
}
void engine_capture(engine_t *e,int enable,uint64_t now) {
    e->capture=(uint8_t)!!enable; if(enable) { e->generation++;e->capture_since=now; }
    memset(e->windows,0,sizeof(e->windows)); engine_event(e,255,EV_CAPTURE,e->capture,now);
}
void engine_rx(engine_t *e,cs_can_t *f) {
    unsigned src=f->side,dst=src^1u; f->frame_id=++e->frame_id; f->crc_ok=1; e->counter[src][0]++;
    if(e->capture&&f->t>=e->capture_since) e->emit(CS_CAN_RX,f,sizeof(*f),e->context);
    if(!e->bridge) return;
    forward_queue_t *q=&e->queues[dst];
    if((uint16_t)(q->write-q->read)>=BRIDGE_QUEUE) {
        engine_tx(e,f,dst,TX_DROPPED,-1,f->t); engine_event(e,dst,EV_TX_OVERFLOW,f->frame_id,f->t); return;
    }
    q->items[q->write++%BRIDGE_QUEUE]=(forward_t){*f,f->t+DELIVERY_US};
    engine_tx(e,f,dst,TX_PENDING,2,f->t);
}
int engine_take(engine_t *e,unsigned dst,uint64_t now,forward_t *out) {
    forward_queue_t *q=&e->queues[dst];
    while(q->read!=q->write) {
        forward_t f=q->items[q->read++%BRIDGE_QUEUE];
        if(now>=f.deadline) { engine_tx(e,&f.frame,dst,TX_EXPIRED,-1,now); engine_event(e,dst,EV_EXPIRED,f.frame.frame_id,now); }
        else { *out=f; return 1; }
    }
    return 0;
}
int engine_profile(engine_t *e,unsigned ch,unsigned range,const cal_profile_t *p) {
    if(ch>=8||range>1||!p->version) return -1;
    if(p->linear) {
        if(p->linear!=1||!isfinite(p->zero)||p->zero<=2||p->zero>=4093||!isfinite(p->gain)||p->gain<=0||p->gain>.1f) return -1;
        e->profiles[ch][range]=*p; return 0;
    }
    if(p->count<2||p->count>PROFILE_POINTS) return -1;
    for(unsigned i=0;i<p->count;i++) {
        if(p->points[i].raw>4095||!isfinite(p->points[i].volts)||p->points[i].volts<0||p->points[i].volts>(range?15.f:3.3f)) return -1;
        if(i&&(p->points[i].raw<p->points[i-1].raw+2||p->points[i].volts<=p->points[i-1].volts)) return -1;
    }
    e->profiles[ch][range]=*p; return 0;
}
void engine_coefficients(const engine_t *e,unsigned ch,unsigned range,cs_coefficients_t *out) {
    const cal_profile_t *p=&e->profiles[ch][range];
    out->channel=ch;out->range=range;out->version=p->version;
    if(p->linear) { out->source=1;out->a=p->gain;out->b=-p->zero*p->gain; }
    else if(p->count) { out->source=2;out->a=NAN;out->b=NAN; }
    else { out->source=0;out->a=(3.3f/4095.f)*(range?6.17f:1.47f);out->b=-3.3f*.47f; }
}
static float convert(const cal_profile_t *p,uint16_t raw,unsigned range,uint16_t *q) {
    if(p->linear) return (raw-p->zero)*p->gain;
    /* R1=100k to VREF, R3=47k to input; R2=10k to GND when OD low.
     * Vin = Vadc*(1+R3/R1+[R3/R2]) - VREF*(R3/R1).
     * Assume VREF=VDDA=3.3 V until measured calibration replaces this model. */
    if(!p->count) { *q|=Q_UNCAL; return raw*(3.3f/4095.f)*(range?6.17f:1.47f)-3.3f*.47f; }
    if(raw<p->points[0].raw||raw>p->points[p->count-1].raw) { *q|=Q_OUTSIDE|Q_UNCAL; return NAN; }
    for(unsigned i=1;i<p->count;i++) if(raw<=p->points[i].raw) {
        cal_point_t a=p->points[i-1],b=p->points[i]; return a.volts+(b.volts-a.volts)*(raw-a.raw)/(b.raw-a.raw);
    }
    return NAN;
}
void engine_range(engine_t *e,unsigned ch,unsigned range,uint64_t now,uint32_t settle) {
    e->range[ch]=(uint8_t)range; e->settle_until[ch]=now+settle;
    memset(&e->windows[ch],0,sizeof(e->windows[ch])); engine_event(e,255,EV_RANGE,(ch<<8)|range,now);
}
void engine_analog(engine_t *e,const uint16_t raw[8],uint64_t t) {
    if(!e->capture) return;
    for(unsigned c=0;c<8;c++) {
        analog_window_t *w=&e->windows[c]; unsigned range=e->range[c];
        if(!w->count) w->start=t;
        w->sum+=raw[c]; w->sum2+=(float)raw[c]*raw[c];
        if(raw[c]<=2||raw[c]>=4093) w->quality|=Q_CLIP;
        if(t<e->settle_until[c]) w->quality|=Q_SETTLE;
        w->volts+=convert(&e->profiles[c][range],raw[c],range,&w->quality);
        if(++w->count==16) {
            float mean=w->sum/16.f, volts=w->volts/16.f, var=w->sum2/16.f-mean*mean;
            if(volts<0||volts>(range?15.f:3.3f)) w->quality|=Q_RANGE;
            if(w->quality&(Q_SETTLE|Q_OUTSIDE)) volts=NAN;
            cs_adc_t v={w->start,(uint8_t)c,(uint8_t)range,w->quality,mean,sqrtf(var>0?var:0),volts,e->profiles[c][range].version};
            if(e->enabled[c]) e->emit(CS_ADC,&v,sizeof(v),e->context);
            memset(w,0,sizeof(*w));
        }
    }
}
