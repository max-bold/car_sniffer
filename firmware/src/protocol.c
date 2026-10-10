#include "protocol.h"
#include <string.h>
uint16_t cs_u16(const uint8_t *p) { return (uint16_t)(p[0]|(uint16_t)p[1]<<8); }
uint32_t cs_u32(const uint8_t *p) { return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static void put32(uint8_t *p,uint32_t v) { for(unsigned i=0;i<4;i++) p[i]=(uint8_t)(v>>(8*i)); }
uint32_t cs_crc32(const uint8_t *p,size_t n) {
    uint32_t c=0xffffffffu;
    while(n--) { c^=*p++; for(unsigned i=0;i<8;i++) c=(c>>1)^((0u-(c&1u))&0xedb88320u); }
    return ~c;
}
size_t cs_encode(uint8_t *dst,uint8_t kind,uint32_t seq,const void *payload,uint16_t len) {
    if(len>CS_MAX_PAYLOAD || kind<1 || kind>9) return 0;
    dst[0]='C'; dst[1]='S'; dst[2]=1; dst[3]=kind; dst[4]=(uint8_t)len; dst[5]=(uint8_t)(len>>8);
    put32(dst+6,seq); if(len) memcpy(dst+10,payload,len); put32(dst+10+len,cs_crc32(dst,10+len)); return 14+len;
}
static void discard(cs_parser_t *p,unsigned n) { memmove(p->buffer,p->buffer+n,p->used-n); p->used=(uint16_t)(p->used-n); }
void cs_feed(cs_parser_t *p,const uint8_t *src,size_t n,cs_packet_fn cb,void *ctx) {
    while(n--) {
        if(p->used==CS_MAX_PACKET) discard(p,1);
        p->buffer[p->used++]=*src++;
        while(p->used>=CS_HEADER) {
            uint8_t *b=p->buffer;
            if(b[0]!='C'||b[1]!='S') { discard(p,1); continue; }
            uint16_t len=cs_u16(b+4);
            if(b[2]!=1||b[3]<1||b[3]>9||len>CS_MAX_PAYLOAD) { p->bad_header++; discard(p,1); continue; }
            unsigned total=14u+len;
            if(p->used<total) break;
            if(cs_crc32(b,total-4)!=cs_u32(b+total-4)) { p->bad_crc++; discard(p,1); continue; }
            uint32_t seq=cs_u32(b+6),delta=seq-p->last_seq;
            if(p->has_seq&&delta!=1) p->gaps+=(delta>1&&delta<0x80000000u)?delta-1:1;
            p->has_seq=1; p->last_seq=seq; cb(b[3],seq,b+10,len,ctx); discard(p,total);
        }
    }
}
