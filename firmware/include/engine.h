#ifndef CS_ENGINE_H
#define CS_ENGINE_H
#include "protocol.h"
#define BRIDGE_QUEUE 64u
#define DELIVERY_US 20000u
#define PROFILE_POINTS 32u
typedef struct { uint16_t raw; float volts; } cal_point_t;
typedef struct { uint32_t version; uint8_t count; cal_point_t points[PROFILE_POINTS]; } cal_profile_t;
typedef struct { cs_can_t frame; uint64_t deadline; } forward_t;
typedef struct { forward_t items[BRIDGE_QUEUE]; uint16_t read,write; } forward_queue_t;
typedef struct { float sum,sum2,volts; uint16_t quality; uint8_t count; uint64_t start; } analog_window_t;
typedef void (*emit_fn)(uint8_t,const void *,uint16_t,void *);
typedef struct {
    forward_queue_t queues[2];
    cal_profile_t profiles[8][2];
    analog_window_t windows[8];
    uint64_t settle_until[8];
    uint64_t capture_since;
    uint32_t rate[2],counter[2][8],frame_id,generation;
    uint8_t bridge,capture,confirmed[2],range[8],enabled[8];
    emit_fn emit; void *context;
} engine_t;
void engine_init(engine_t *e,emit_fn emit,void *context);
int engine_bridge(engine_t *e,int enable,uint64_t now);
void engine_capture(engine_t *e,int enable,uint64_t now);
void engine_rx(engine_t *e,cs_can_t *frame);
int engine_take(engine_t *e,unsigned destination,uint64_t now,forward_t *out);
void engine_tx(engine_t *e,const cs_can_t *f,unsigned destination,uint8_t state,int8_t ack,uint64_t now);
void engine_drop(engine_t *e,unsigned destination,uint64_t now);
int engine_profile(engine_t *e,unsigned ch,unsigned range,const cal_profile_t *p);
void engine_analog(engine_t *e,const uint16_t raw[8],uint64_t t);
void engine_range(engine_t *e,unsigned ch,unsigned range,uint64_t now,uint32_t settling_us);
void engine_event(engine_t *e,unsigned side,unsigned code,uint32_t detail,uint64_t now);
#endif
