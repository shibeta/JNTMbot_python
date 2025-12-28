@echo off
:: 设置环境
chcp 65001 >nul
pushd "%~dp0"

:: 清理屏幕，准备输出
cls
title ViGEmBus 驱动安装程序
echo =========================================
echo  ViGEmBus 虚拟手柄驱动安装程序
echo =========================================
echo.

:: 查找 MSI 安装文件
echo 正在查找驱动安装程序...
set "RELEASE_MSI_PATH=%~dp0虚拟手柄驱动ViGEmBusSetup_x64.msi"
set "SOURCE_MSI_PATH=%~dp0assets\虚拟手柄驱动ViGEmBusSetup_x64.msi"
set "MSI_PATH="

:: 首先检查 Release (打包后) 的路径
if exist "%RELEASE_MSI_PATH%" (
    set "MSI_PATH=%RELEASE_MSI_PATH%"
)

:: 如果上面没找到，再检查 Source (源代码直接运行) 的路径
if not defined MSI_PATH (
    if exist "%SOURCE_MSI_PATH%" (
        set "MSI_PATH=%SOURCE_MSI_PATH%"
    )
)

:: 如果两个路径都找不到，则报错退出
if not defined MSI_PATH (
    echo.
    echo 错误：未能在以下预期位置找到 虚拟手柄驱动ViGEmBusSetup_x64.msi：
    echo   - %RELEASE_MSI_PATH%
    echo   - %SOURCE_MSI_PATH%
    echo.
    echo 请确保脚本和程序文件完整。
    goto:end
)

echo 已找到安装程序: %MSI_PATH%
echo.

:: 执行安装
echo 开始安装驱动。请在安装程序中勾选同意用户条款，并点击“Install”。

echo 如果弹出UAC用户账户控制窗口，请选择“是”。
msiexec /package "%MSI_PATH%"

:: 检查安装是否成功 (msiexec的错误码0和3010都表示成功)
if %errorlevel% EQU 3010 (
    goto:success
)
if %errorlevel% EQU 0 (
    goto:success
)

:: 如果失败
echo.
echo 错误：驱动安装失败，错误码: %errorlevel%
echo 您可以尝试手动运行 "%MSI_PATH%" 进行安装。
goto:end

:success
echo.
echo =========================================
echo  驱动安装成功！
echo =========================================
echo.
echo 现在您可以重新启动您的应用程序了。

:end
echo.
echo 按任意键退出...
pause >nul