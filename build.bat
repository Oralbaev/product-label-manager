@echo off
setlocal

title BotaShop Build
echo.
echo =============================================
echo   BotaShop Build Script
echo =============================================
echo.

:: Verify Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found on PATH.
    exit /b 1
)
echo [OK] Python found.

:: Install/update Python dependencies
echo.
echo [INFO] Installing Python dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet -r botaprint/requirements.txt
python -m pip install --quiet waitress whitenoise pyinstaller
if errorlevel 1 (
    echo [ERROR] pip install failed.
    exit /b 1
)
echo [OK] Dependencies installed.

:: Collect Django static files
echo.
echo [INFO] Collecting Django static files...
python manage.py collectstatic --noinput --clear
if errorlevel 1 (
    echo [ERROR] collectstatic failed.
    exit /b 1
)
echo [OK] Static files collected.

:: Clean previous builds
echo.
echo [INFO] Cleaning previous build artifacts...
if exist dist\BotaShop   rmdir /s /q dist\BotaShop
if exist build\BotaShop  rmdir /s /q build\BotaShop
echo [OK] Cleaned.

:: PyInstaller build
echo.
echo [INFO] Building BotaShop.exe with PyInstaller (onedir)...
echo        This may take several minutes on first run.
pyinstaller BotaShop.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    exit /b 1
)
if not exist "dist\BotaShop\BotaShop.exe" (
    echo [ERROR] dist\BotaShop\BotaShop.exe not found after build.
    exit /b 1
)
echo [OK] PyInstaller build complete: dist\BotaShop\BotaShop.exe

:: Inno Setup installer
echo.
echo [INFO] Looking for Inno Setup 6...

set "ISCC="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if exist "C:\InnoSetup6\ISCC.exe"                        set "ISCC=C:\InnoSetup6\ISCC.exe"

if "%ISCC%"=="" (
    echo [WARN] Inno Setup 6 not found. Skipping installer creation.
    echo        Download: https://jrsoftware.org/isdl.php
    echo.
    echo        PyInstaller bundle ready at:
    echo          dist\BotaShop\BotaShop.exe
    goto :done
)

echo [OK] Found Inno Setup.
echo [INFO] Compiling installer...
"%ISCC%" BotaShopSetup.iss
if errorlevel 1 (
    echo [ERROR] Inno Setup compilation failed.
    exit /b 1
)

:done
echo.
echo =============================================
echo   Build complete!
echo =============================================
if exist "dist\BotaShopSetup.exe" (
    echo   Installer : dist\BotaShopSetup.exe
) else (
    echo   Bundle    : dist\BotaShop\BotaShop.exe
)
echo.

endlocal
