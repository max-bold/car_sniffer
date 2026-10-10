# STM32F407 toolchain

Среда: Windows / PowerShell. Плата **STM32F4VE**, MCU **STM32F407VET6**, программатор **ST-Link**, интерфейс **SWD**. Разработка, сборка, прошивка и отладка — из CLI.

Инструменты установлены по информации владельца; перед работой проверь их доступность. Не предполагай конкретные пути и версии: используй PATH или полный путь к установленному инструменту.

| Инструмент | Назначение | Минимальная проверка |
|---|---|---|
| Git | История изменений и работа с репозиторием | `git --version` |
| CMake | Конфигурация сборки с ARM toolchain | `cmake --version` |
| Ninja | Выполнение сборки, подготовленной CMake | `ninja --version` |
| STM32CubeCLT: arm-none-eabi-gcc | Компиляция и линковка прошивки для ARM Cortex-M | `arm-none-eabi-gcc --version` |
| STM32CubeCLT: arm-none-eabi-gdb | Отладка ELF через GDB-сервер | `arm-none-eabi-gdb --version` |
| STM32CubeCLT: STM32_Programmer_CLI | Подключение через ST-Link, прошивка и проверка памяти | `STM32_Programmer_CLI -h` |
| STM32CubeMX | Настройка выводов, тактирования и периферии; генерация кода из `.ioc` | Запустить STM32CubeMX и открыть Help → About |
| OpenOCD | GDB-сервер для отладки через ST-Link/SWD | `openocd --version` |
| Python 3 | Скрипты автоматизации, обмен с платой и тесты | `py -3 --version` |

Пакеты Python: **pyserial** — UART/COM; **python-can** — работа с CAN через совместимый адаптер; **pytest** — тесты; **numpy** — обработка числовых данных.

```powershell
py -3 -m pip show pyserial python-can pytest numpy
py -3 -c "import serial, can, pytest, numpy; print('Python packages OK')"
```

Если используется виртуальное окружение, выполняй проверки через его `python` вместо `py -3`. Для поиска исполняемых файлов в PowerShell используй `Get-Command <имя>` или `where.exe <имя>`.

Проверка подключения (плата запитана, ST-Link подключён по SWD):

```powershell
STM32_Programmer_CLI -c port=SWD
```

Запуск сервера отладки; затем в другом терминале открыть ELF и подключить GDB:

```powershell
openocd -f interface/stlink.cfg -f target/stm32f4x.cfg
arm-none-eabi-gdb path/to/firmware.elf
# В консоли GDB:
target remote localhost:3333
```

Для сборки используй настройки CMake/presets и ARM toolchain-файл самого репозитория. Не подменяй ARM-компилятор системным компилятором Windows. Перед изменением генерируемого кода учитывай `.ioc` и секции `USER CODE`.

Документация: [STM32CubeCLT](https://www.st.com/en/development-tools/stm32cubeclt.html), [STM32CubeMX](https://www.st.com/content/st_com/en/stm32cubemx.html), [OpenOCD](https://www.openocd.org/doc/html/Running.html).
