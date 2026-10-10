$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$cube = Join-Path $root 'firmware/vendor/STM32CubeF4'
if (-not (Test-Path "$cube/.git")) {
    git clone --depth 1 --branch v1.28.1 https://github.com/STMicroelectronics/STM32CubeF4.git $cube
    if ($LASTEXITCODE) { throw 'CubeF4 clone failed' }
}
git -C $cube checkout 83778d5c95cb01695c7facbf095db3ab445532ea
git -C $cube submodule update --init --depth 1 Drivers/CMSIS/Device/ST/STM32F4xx Drivers/STM32F4xx_HAL_Driver
if ($LASTEXITCODE) { throw 'HAL/CMSIS checkout failed' }
if (-not (Test-Path "$root/.venv/Scripts/python.exe")) { py -3 -m venv "$root/.venv" }
& "$root/.venv/Scripts/python.exe" -m pip install -r "$root/requirements-lock.txt"
if ($LASTEXITCODE) { throw 'Python dependencies failed' }
