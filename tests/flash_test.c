/* Run actual storage code against a simulated NOR Flash with failing writes. */
#include <windows.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>
#include "calibration_flash.h"
#include "stm32f4xx_hal.h"
static int fail_after=-1,writes;
static unsigned char snapshot[0x40000];
static engine_t e;
int HAL_FLASH_Unlock(void){return 0;}
int HAL_FLASH_Lock(void){return 0;}
int HAL_FLASHEx_Erase(FLASH_EraseInitTypeDef *v,uint32_t *error){
    (void)error;assert(v->NbSectors==1&&(v->Sector==6||v->Sector==7));
    memset((void *)(uintptr_t)(v->Sector==6?0x08040000:0x08060000),255,0x20000);return 0;
}
int HAL_FLASH_Program(uint32_t type,uint32_t address,uint32_t value){
    (void)type;if(fail_after>=0&&writes>=fail_after)return 1;
    assert(address>=0x08040000&&address<0x08080000);writes++;
    *(uint32_t *)(uintptr_t)address&=value;return 0;
}
int main(void){
    void *memory=VirtualAlloc((void *)0x08040000,0x40000,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    assert(memory==(void *)0x08040000);memset(memory,255,0x40000);
    engine_init(&e,NULL,NULL);calibration_load(&e);assert(!e.profiles[0].version);
    /* A CRC-valid legacy CAL1 record must not apply to the new circuit,
     * and merely booting must leave its Flash contents intact. */
    struct {uint32_t magic,generation,size;cal_profile_t profiles[8][2];uint32_t crc,commit;} legacy={0};
    legacy.magic=0x314c4143u;legacy.generation=9;legacy.size=sizeof(legacy);legacy.commit=0x434f4d54u;
    for(unsigned c=0;c<8;c++)for(unsigned r=0;r<2;r++)
        legacy.profiles[c][r]=(cal_profile_t){.version=7,.linear=1,.zero=1200.f,.gain=.002f};
    legacy.crc=cs_crc32((const uint8_t *)&legacy,(size_t)((const uint8_t *)&legacy.crc-(const uint8_t *)&legacy));
    memcpy(memory,&legacy,sizeof(legacy));calibration_load(&e);
    assert(!e.profiles[0].version&&!e.profiles[7].version&&!memcmp(memory,&legacy,sizeof(legacy)));
    for(unsigned c=0;c<8;c++){
        cal_profile_t p={.version=1,.linear=1,.zero=300.25f,.gain=.004f};assert(!engine_profile(&e,c,1,&p));
    }
    assert(!calibration_save(&e));memcpy(snapshot,memory,sizeof(snapshot));
    for(unsigned c=0;c<8;c++){e.profiles[c].zero=400.5f;e.profiles[c].version=2;}
    writes=0;assert(!calibration_save(&e));int words=writes;
    calibration_load(&e);assert(e.profiles[0].zero==400.5f);
    /* Interrupt before every word, including the commit marker. Old slot survives. */
    for(int n=0;n<words;n++){
        memcpy(memory,snapshot,sizeof(snapshot));
        for(unsigned c=0;c<8;c++){e.profiles[c].zero=400.5f;e.profiles[c].version=2;}
        fail_after=n;writes=0;assert(calibration_save(&e));calibration_load(&e);
        assert(e.profiles[0].zero==300.25f&&e.profiles[7].version==1);
    }
    memcpy(memory,snapshot,sizeof(snapshot));fail_after=-1;writes=0;
    for(unsigned c=0;c<8;c++){e.profiles[c].zero=400.5f;e.profiles[c].version=2;}
    assert(!calibration_save(&e));((unsigned char *)memory)[0x20020]^=1;
    calibration_load(&e);assert(e.profiles[0].zero==300.25f);
    /* Factory reset is a committed newer empty record, not a two-sector erase. */
    memcpy(snapshot,memory,sizeof(snapshot));
    fail_after=-1;writes=0;assert(!calibration_reset());int reset_words=writes;
    calibration_load(&e);
    for(unsigned c=0;c<8;c++)assert(!e.profiles[c].version);
    for(int n=0;n<reset_words;n++){
        memcpy(memory,snapshot,sizeof(snapshot));fail_after=n;writes=0;
        assert(calibration_reset());calibration_load(&e);
        assert(e.profiles[0].zero==300.25f&&e.profiles[7].version==1);
    }
    memcpy(memory,snapshot,sizeof(snapshot));fail_after=-1;assert(!calibration_reset());
    calibration_load(&e);assert(!e.profiles[7].version);
    for(unsigned c=0;c<8;c++){
        cal_profile_t p={.version=3,.linear=1,.zero=500.f,.gain=.003f};assert(!engine_profile(&e,c,1,&p));
    }
    assert(!calibration_save(&e));calibration_load(&e);assert(e.profiles[7].version==3);
    puts("Calibration Flash: defaults, reload, dual slots, CRC, interrupted saves/resets and recalibration OK");
    VirtualFree(memory,0,MEM_RELEASE);return 0;
}
