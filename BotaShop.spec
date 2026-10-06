# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for BotaShop.exe  (onedir build).
#
# Run from the project root AFTER running build.bat, or manually:
#     pyinstaller BotaShop.spec --clean
#
# Output: dist/BotaShop/BotaShop.exe

import os
import sys
from pathlib import Path

# Find Django installation for locale/template data
import django
_DJANGO_ROOT = Path(django.__file__).parent

block_cipher = None

# ── Data files ─────────────────────────────────────────────────────────────────
# Format: (source, destination_inside_bundle)
datas = [
    # Project templates
    ('templates',            'templates'),
    # Django migrations (Python files Django imports at runtime)
    ('shop/migrations',      'shop/migrations'),
    # BotaPrint font directory (place DejaVuSans-Bold.ttf here to bundle it)
    ('botaprint/fonts',      'botaprint/fonts'),
    # Django locale files for Russian / Kazakh UI messages
    (str(_DJANGO_ROOT / 'conf' / 'locale'),
     'django/conf/locale'),
    (str(_DJANGO_ROOT / 'contrib' / 'admin' / 'locale'),
     'django/contrib/admin/locale'),
    # Django admin templates (needed when accessing /admin/)
    (str(_DJANGO_ROOT / 'contrib' / 'admin' / 'templates'),
     'django/contrib/admin/templates'),
]

# Collected static files (created by "python manage.py collectstatic")
if os.path.exists('staticfiles'):
    datas.append(('staticfiles', 'staticfiles'))

# ── Hidden imports ─────────────────────────────────────────────────────────────
hiddenimports = [
    # ── Django core ──
    'django.contrib.admin',
    'django.contrib.admin.apps',
    'django.contrib.auth',
    'django.contrib.auth.password_validation',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sessions.backends.db',
    'django.contrib.messages',
    'django.contrib.messages.storage.fallback',
    'django.contrib.staticfiles',
    'django.db.backends.sqlite3',
    'django.template.backends.django',
    'django.template.loaders.filesystem',
    'django.template.loaders.app_directories',
    'django.middleware.security',
    'django.middleware.common',
    'django.middleware.csrf',
    'django.middleware.clickjacking',
    # ── Project apps ──
    'config.settings',
    'config.urls',
    'config.wsgi',
    'shop',
    'shop.admin',
    'shop.apps',
    'shop.forms',
    'shop.label_service',
    'shop.models',
    'shop.services',
    'shop.printing_service',
    'shop.views',
    'shop.urls',
    'shop.migrations',
    'shop.migrations.0001_initial',
    'shop.migrations.0002_alter_productvariant_color_alter_productvariant_size',
    'shop.migrations.0003_alter_category_options_alter_product_options_and_more',
    'shop.migrations.0004_productvariant_is_active_printjob',
    # ── BotaPrint ──
    'botaprint',
    'botaprint.main',
    'botaprint.printing',
    # ── FastAPI / Uvicorn ──
    'fastapi',
    'fastapi.middleware.cors',
    'fastapi.responses',
    'fastapi.routing',
    'fastapi.encoders',
    'uvicorn',
    'uvicorn.config',
    'uvicorn.server',
    'uvicorn.logging',
    'uvicorn.main',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    # 'uvicorn.loops.none' — not a real module in this uvicorn version, skip
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    # h11 is uvicorn's HTTP/1.1 parser (always available as uvicorn dep)
    'h11',
    'h11._readers',
    'h11._writers',
    'h11._util',
    'h11._events',
    'h11._state',
    # starlette (FastAPI depends on it)
    'starlette',
    'starlette.routing',
    'starlette.middleware',
    'starlette.middleware.cors',
    'starlette.responses',
    'starlette.requests',
    'starlette.background',
    'starlette.concurrency',
    'starlette.datastructures',
    'starlette.exceptions',
    'starlette.types',
    # anyio (uvicorn uses this for async I/O)
    'anyio',
    'anyio._backends._asyncio',
    'anyio.abc',
    'anyio.streams',
    'anyio.streams.memory',
    # ── Waitress ──
    'waitress',
    'waitress.server',
    'waitress.task',
    'waitress.channel',
    'waitress.parser',
    # ── WhiteNoise ──
    'whitenoise',
    'whitenoise.middleware',
    'whitenoise.storage',
    # ── pywin32 ──
    'win32print',
    'win32ui',
    'win32con',
    'win32gui',
    'pywintypes',
    'win32timezone',         # required by pywin32
    # ── Pillow ──
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageWin',
    # ── ReportLab ──
    'reportlab',
    'reportlab.pdfgen',
    'reportlab.pdfgen.canvas',
    'reportlab.lib.units',
    'reportlab.graphics.barcode',
    'reportlab.graphics.barcode.code128',
    'reportlab.pdfbase',
    'reportlab.pdfbase.ttfonts',
    'reportlab.pdfbase.pdfmetrics',
    # ── pypdf ──
    'pypdf',
    # ── other ──
    'pydantic',
    'pydantic_core',
    'email',
    'email.mime',
    'email.mime.text',
    'logging.handlers',
    'ctypes',
    'ctypes.windll',
]

# ── Analysis ───────────────────────────────────────────────────────────────────
a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'psycopg2',
        'psycopg2-binary',
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BotaShop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,       # no console window for the end user
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,           # add icon.ico here when available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        'vcruntime140.dll',
        'python3*.dll',
        'pywintypes*.dll',
        'win32ui.pyd',
        'win32print.pyd',
    ],
    name='BotaShop',
)
