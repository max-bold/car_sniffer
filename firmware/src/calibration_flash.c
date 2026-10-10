#include "calibration_flash.h"
#include "stm32f4xx_hal.h"
#include <string.h>
#include <stddef.h>

/* STM32F407VE sectors 6/7, excluded from the application linker region.
 * Inactive slot is erased; commit word is programmed last. No mass erase. */
#define CAL_MAGIC 0x314c4143u
#define CAL_COMMIT 0x434f4d54u
typedef struct {
    uint32_t magic,generation,size;
    cal_profile_t profiles[8][2];
    uint32_t crc,commit;
} record_t;
static record_t staging;
static const record_t *const slots[2]={(const record_t *)0x08040000u,(const record_t *)0x08060000u};
static int valid(const record_t *r) {
    return r->magic==CAL_MAGIC&&r->size==sizeof(*r)&&r->commit==CAL_COMMIT&&
        r->crc==cs_crc32((const uint8_t *)r,offsetof(record_t,crc));
}
static int newest(void) {
    int a=valid(slots[0]),b=valid(slots[1]);
    if(!a&&!b)return -1;
    if(a&&b)return (int32_t)(slots[1]->generation-slots[0]->generation)>0?1:0;
    return a?0:1;
}
void calibration_load(engine_t *e) {
    memset(e->profiles,0,sizeof(e->profiles));
    int slot=newest();if(slot<0)return;
    for(unsigned c=0;c<8;c++)for(unsigned r=0;r<2;r++)
        engine_profile(e,c,r,&slots[slot]->profiles[c][r]);
}
int calibration_save(const engine_t *e) {
    for(unsigned c=0;c<8;c++)for(unsigned r=0;r<2;r++)if(!e->profiles[c][r].linear)return -1;
    int previous=newest(),next=previous==0?1:0;
    memset(&staging,0,sizeof(staging));staging.magic=CAL_MAGIC;
    staging.generation=previous<0?1:slots[previous]->generation+1;
    staging.size=sizeof(staging);memcpy(staging.profiles,e->profiles,sizeof(e->profiles));
    staging.crc=cs_crc32((const uint8_t *)&staging,offsetof(record_t,crc));staging.commit=CAL_COMMIT;
    FLASH_EraseInitTypeDef erase={.TypeErase=FLASH_TYPEERASE_SECTORS,.Sector=next?FLASH_SECTOR_7:FLASH_SECTOR_6,.NbSectors=1,.VoltageRange=FLASH_VOLTAGE_RANGE_3};
    uint32_t error;int failed=0;
    if(HAL_FLASH_Unlock()!=HAL_OK)return -1;
    /* Capture/bridge must already be stopped. Single-bank Flash stalls CPU while busy.
     * Leave interrupts enabled so HAL timeout ticks remain available between operations. */
    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_EOP|FLASH_FLAG_OPERR|FLASH_FLAG_WRPERR|FLASH_FLAG_PGAERR|FLASH_FLAG_PGPERR|FLASH_FLAG_PGSERR);
    if(HAL_FLASHEx_Erase(&erase,&error)!=HAL_OK)failed=1;
    for(size_t i=0;!failed&&i<sizeof(staging);i+=4) {
        uint32_t word;memcpy(&word,(const uint8_t *)&staging+i,4);
        if(HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD,(uint32_t)(uintptr_t)slots[next]+(uint32_t)i,word)!=HAL_OK)failed=1;
    }
    HAL_FLASH_Lock();
    return failed||!valid(slots[next])?-1:0;
}
