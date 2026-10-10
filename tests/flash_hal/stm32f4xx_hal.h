#ifndef FLASH_TEST_HAL_H
#define FLASH_TEST_HAL_H
#include <stdint.h>
#define HAL_OK 0
#define FLASH_TYPEERASE_SECTORS 0
#define FLASH_SECTOR_6 6
#define FLASH_SECTOR_7 7
#define FLASH_VOLTAGE_RANGE_3 3
#define FLASH_TYPEPROGRAM_WORD 0
#define FLASH_FLAG_EOP 0
#define FLASH_FLAG_OPERR 0
#define FLASH_FLAG_WRPERR 0
#define FLASH_FLAG_PGAERR 0
#define FLASH_FLAG_PGPERR 0
#define FLASH_FLAG_PGSERR 0
#define __HAL_FLASH_CLEAR_FLAG(x) ((void)(x))
typedef struct { uint32_t TypeErase,Sector,NbSectors,VoltageRange; } FLASH_EraseInitTypeDef;
int HAL_FLASH_Unlock(void);
int HAL_FLASH_Lock(void);
int HAL_FLASHEx_Erase(FLASH_EraseInitTypeDef *,uint32_t *);
int HAL_FLASH_Program(uint32_t,uint32_t,uint32_t);
#endif
