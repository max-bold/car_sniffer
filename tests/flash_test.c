/* Run actual storage code against a simulated NOR Flash with failing writes. */
#include <windows.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
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
    engine_init(&e,NULL,NULL);calibration_load(&e);assert(!e.profiles[0][0].version);
    for(unsigned c=0;c<8;c++)for(unsigned r=0;r<2;r++){
        cal_profile_t p={.version=1,.linear=1,.zero=300.25f,.gain=.004f};assert(!engine_profile(&e,c,r,&p));
    }
    assert(!calibration_save(&e));memcpy(snapshot,memory,sizeof(snapshot));
    for(unsigned c=0;c<8;c++)for(unsigned r=0;r<2;r++){e.profiles[c][r].zero=400.5f;e.profiles[c][r].version=2;}
    writes=0;assert(!calibration_save(&e));int words=writes;
    calibration_load(&e);assert(e.profiles[0][0].zero==400.5f);
    /* Interrupt before every word, including the commit marker. Old slot survives. */
    for(int n=0;n<words;n++){
        memcpy(memory,snapshot,sizeof(snapshot));
        for(unsigned c=0;c<8;c++)for(unsigned r=0;r<2;r++){e.profiles[c][r].zero=400.5f;e.profiles[c][r].version=2;}
        fail_after=n;writes=0;assert(calibration_save(&e));calibration_load(&e);
        assert(e.profiles[0][0].zero==300.25f&&e.profiles[7][1].version==1);
    }
    memcpy(memory,snapshot,sizeof(snapshot));fail_after=-1;writes=0;
    for(unsigned c=0;c<8;c++)for(unsigned r=0;r<2;r++){e.profiles[c][r].zero=400.5f;e.profiles[c][r].version=2;}
    assert(!calibration_save(&e));((unsigned char *)memory)[0x20020]^=1;
    calibration_load(&e);assert(e.profiles[0][0].zero==300.25f);
    puts("Calibration Flash: defaults, reload, dual slots, CRC and interrupted writes OK");
    VirtualFree(memory,0,MEM_RELEASE);return 0;
}
