@echo off
cd /d "%~dp0"

echo ================================================
echo   JM漫画下载器 - 打包 EXE
echo ================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装并加入 PATH
    goto :fail
)

python -m PyInstaller "JM漫画下载器.spec" --noconfirm
if errorlevel 1 goto :fail

move /y "dist\JM漫画下载器.exe" "JM漫画下载器.exe" >nul
rd /s /q build 2>nul
rd /s /q dist 2>nul

echo.
echo [完成] 已生成: %~dp0JM漫画下载器.exe
pause
exit /b 0

:fail
echo.
echo [失败] 打包未完成，请检查上方错误信息（首次使用先执行: pip install pyinstaller）
pause
exit /b 1
