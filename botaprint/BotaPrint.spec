# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for BotaPrint.exe
#
# Build command (run from the botaprint/ directory):
#   pyinstaller BotaPrint.spec
#
# Or from the project root:
#   pyinstaller botaprint/BotaPrint.spec --distpath botaprint/dist --workpath botaprint/build
#
# Requirements before building:
#   pip install pyinstaller

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # Bundle the fonts/ directory so DejaVuSans-Bold.ttf is available in the exe
    datas=[('fonts', 'fonts')],
    hiddenimports=[
        'win32timezone',
        'win32print',
        'win32ui',
        'win32con',
        'pywintypes',
        'PIL._imagingtk',
        'PIL.ImageWin',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter'],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='BotaPrint',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,       # keep console visible so the user sees log output
    icon=None,
)
