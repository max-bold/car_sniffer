#ifndef CS_PROTOCOL_H
#define CS_PROTOCOL_H
#include <stdint.h>
#include <stddef.h>
#define CS_MAX_PAYLOAD 1024u
#define CS_HEADER 10u
#define CS_MAX_PACKET (CS_MAX_PAYLOAD + 14u)
enum { CS_COMMAND=1, CS_RESPONSE, CS_STATUS, CS_CAN_RX, CS_TX_STATUS, CS_EVENT, CS_ADC, CS_RAW, CS_AUTO, CS_COEFFICIENTS };
enum { CMD_STATUS=1, CMD_CAN_CONFIG, CMD_BRIDGE, CMD_CAPTURE, CMD_CHANNEL, CMD_PROFILE, CMD_RAW, CMD_CLEAR_COUNTERS, CMD_LOOPBACK, CMD_LINEAR_PROFILE, CMD_SAVE_CALIBRATION, CMD_RELOAD_CALIBRATION, CMD_READ_COEFFICIENTS, CMD_RESET_CALIBRATION };
enum { Q_FACTORY_DEFAULTS=1, Q_UNCAL=Q_FACTORY_DEFAULTS, Q_CLIP=2, Q_SETTLE=4, Q_RANGE=8, Q_OUTSIDE=16, Q_DMA_LOSS=32 };
enum { TX_PENDING, TX_SENT, TX_FAILED, TX_EXPIRED, TX_DROPPED };
enum { EV_LEC=1, EV_STATE, EV_RX_OVERFLOW, EV_TX_OVERFLOW, EV_EXPIRED, EV_USB_LOSS, EV_RECOVERY, EV_BRIDGE_STOP, EV_RANGE, EV_DMA_LOSS, EV_CAPTURE, EV_LOOPBACK, EV_RECONFIG_DROP };
#pragma pack(push,1)
typedef struct { uint64_t t; uint32_t frame_id,id; uint8_t side,ide,rtr,dlc,crc_ok,data[8]; } cs_can_t;
typedef struct { uint64_t t; uint32_t frame_id; uint8_t side,state; int8_t ack; } cs_tx_t;
typedef struct { uint64_t t; uint8_t side,code; uint32_t detail,tec,rec; } cs_event_t;
typedef struct { uint64_t t; uint8_t channel,range; uint16_t quality; float raw_mean,raw_std,volts; uint32_t version; } cs_adc_t;
typedef struct { uint64_t t; uint8_t channel,range; uint16_t raw; } cs_raw_t;
typedef struct { uint32_t request; uint8_t channel,range,source; uint32_t version; float a,b; } cs_coefficients_t;
typedef struct { uint64_t t; uint8_t side,stage; uint32_t bitrate; } cs_auto_t;
typedef struct { uint64_t t; uint32_t boot,flags,generation; uint8_t uid[12],bridge,capture,mode[2]; uint32_t rate[2],counters[2][8]; } cs_status_t;
#pragma pack(pop)
typedef void (*cs_packet_fn)(uint8_t kind,uint32_t sequence,const uint8_t *payload,uint16_t length,void *context);
typedef struct { uint8_t buffer[CS_MAX_PACKET]; uint16_t used; uint8_t has_seq; uint32_t last_seq,bad_crc,bad_header,gaps; } cs_parser_t;
uint32_t cs_crc32(const uint8_t *p,size_t n);
size_t cs_encode(uint8_t *dst,uint8_t kind,uint32_t seq,const void *payload,uint16_t length);
void cs_feed(cs_parser_t *p,const uint8_t *src,size_t n,cs_packet_fn callback,void *context);
uint16_t cs_u16(const uint8_t *p);
uint32_t cs_u32(const uint8_t *p);
#endif
