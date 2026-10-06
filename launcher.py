"""
BotaShop Launcher
=================
Единая точка запуска: создаёт базу данных, запускает Django + BotaPrint,
открывает браузер. При повторном запуске только открывает браузер.

При упаковке через PyInstaller запускается как BotaShop.exe (без консоли).
"""

import ctypes
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# ── Data / log paths ───────────────────────────────────────────────────────────
_LOCALAPPDATA = os.environ.get('LOCALAPPDATA', '')
_APP_ROOT = (
    Path(_LOCALAPPDATA) / 'BotaShop'
    if _LOCALAPPDATA
    else Path.home() / 'AppData' / 'Local' / 'BotaShop'
)
_DATA_DIR = _APP_ROOT / 'data'
_LOGS_DIR = _APP_ROOT / 'logs'

for _d in (_DATA_DIR, _LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Redirect sys.stdout / sys.stderr ─────────────────────────────────────────
# In a PyInstaller windowed build (console=False) sys.stdout and sys.stderr are
# None.  Many libraries (including uvicorn.logging.DefaultFormatter) call
# sys.stdout.isatty() which raises AttributeError on None.
# Redirect both to files so every library sees a real file-like object.
if sys.stdout is None:
    sys.stdout = open(str(_LOGS_DIR / 'stdout.log'), 'a', encoding='utf-8', buffering=1)
if sys.stderr is None:
    sys.stderr = open(str(_LOGS_DIR / 'stderr.log'), 'a', encoding='utf-8', buffering=1)

# ── Logging ────────────────────────────────────────────────────────────────────
_log_fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')

def _file_handler(name: str) -> logging.FileHandler:
    h = logging.FileHandler(str(_LOGS_DIR / name), encoding='utf-8')
    h.setFormatter(_log_fmt)
    return h

logging.basicConfig(
    level=logging.INFO,
    handlers=[_file_handler('launcher.log')],
)
logger = logging.getLogger('launcher')

# ── Error dialog (works without a console window) ─────────────────────────────
def _error(title: str, message: str) -> None:
    logger.error('%s: %s', title, message)
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass

# ── Single-instance guard ──────────────────────────────────────────────────────
_MUTEX_NAME = 'BotaShop_SingleInstance_2024'
_mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
if ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
    logger.info('Already running — opening browser.')
    webbrowser.open('http://127.0.0.1:8000/products/')
    sys.exit(0)

logger.info('BotaShop launcher starting (PID %d).', os.getpid())

# ── Bundle / project root path ─────────────────────────────────────────────────
# sys._MEIPASS is set by PyInstaller (both onedir and onefile modes).
if getattr(sys, '_MEIPASS', None):
    _ROOT = Path(sys._MEIPASS)
else:
    _ROOT = Path(__file__).resolve().parent

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger.info('Application root: %s', _ROOT)

# ── Django ─────────────────────────────────────────────────────────────────────
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

try:
    import django
    django.setup()
    logger.info('Django configured.')
except Exception as exc:
    _error('BotaShop — Ошибка', f'Не удалось инициализировать Django:\n{exc}')
    sys.exit(1)

try:
    from django.core.management import call_command
    logger.info('Running database migrations...')
    call_command('migrate', '--run-syncdb', verbosity=0)
    logger.info('Migrations complete.')
except Exception as exc:
    _error('BotaShop — Ошибка', f'Не удалось создать базу данных:\n{exc}')
    sys.exit(1)

try:
    from django.core.wsgi import get_wsgi_application
    _django_wsgi = get_wsgi_application()
    logger.info('Django WSGI application ready.')
except Exception as exc:
    _error('BotaShop — Ошибка', f'Не удалось создать WSGI-приложение:\n{exc}')
    sys.exit(1)

# ── BotaPrint ──────────────────────────────────────────────────────────────────
try:
    from botaprint.main import app as _botaprint_app
    logger.info('BotaPrint app loaded.')
except Exception as exc:
    _error('BotaShop — Ошибка', f'Не удалось загрузить BotaPrint:\n{exc}')
    sys.exit(1)

# ── Thread runners ─────────────────────────────────────────────────────────────
def _run_django() -> None:
    log = logging.getLogger('django_waitress')
    log.addHandler(_file_handler('django.log'))
    log.setLevel(logging.INFO)
    try:
        from waitress import serve
        logger.info('Django starting on http://127.0.0.1:8000 (Waitress).')
        serve(
            _django_wsgi,
            host='127.0.0.1',
            port=8000,
            threads=4,
            channel_timeout=120,
        )
    except Exception as exc:
        logger.exception('Django Waitress server crashed: %s', exc)


def _run_botaprint() -> None:
    # Route all botaprint / uvicorn log records to botaprint.log
    _bp_handler = _file_handler('botaprint.log')
    for _ln in ('botaprint', 'uvicorn', 'uvicorn.error', 'uvicorn.access', 'fastapi'):
        _l = logging.getLogger(_ln)
        _l.addHandler(_bp_handler)
        _l.setLevel(logging.INFO)

    try:
        import asyncio
        import uvicorn

        # ── WHY we use Server directly instead of uvicorn.run() ───────────────
        # uvicorn.run() → Server.serve() → install_signal_handlers()
        # On Windows that falls back to signal.signal(SIGTERM, …).
        # signal.signal() raises ValueError in any non-main thread.
        # Solution: bypass it by monkey-patching install_signal_handlers to a no-op
        # and driving the asyncio event loop ourselves.

        config = uvicorn.Config(
            _botaprint_app,
            host='127.0.0.1',
            port=9100,
            log_level='info',
            access_log=False,
            # log_config=None disables uvicorn's logging setup entirely.
            # Without this, uvicorn.logging.DefaultFormatter.__init__ calls
            # sys.stdout.isatty(), which crashes when sys.stdout is None
            # (PyInstaller console=False / windowed build).
            log_config=None,
        )
        server = uvicorn.Server(config)

        # Disable signal-handler installation — not allowed outside the main thread
        server.install_signal_handlers = lambda: None

        # Create a fresh event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        logger.info('BotaPrint starting on http://127.0.0.1:9100 (Uvicorn).')
        try:
            loop.run_until_complete(server.serve())
        finally:
            loop.close()

    except Exception:
        logger.exception('BotaPrint failed — full traceback:')
        _error(
            'BotaShop — BotaPrint не запустился',
            f'BotaPrint не запустился.\n'
            f'Подробности в журнале:\n'
            f'{_LOGS_DIR / "botaprint.log"}',
        )


# ── Start services ─────────────────────────────────────────────────────────────
_django_thread = threading.Thread(target=_run_django, daemon=True, name='django')
_botaprint_thread = threading.Thread(target=_run_botaprint, daemon=True, name='botaprint')
_django_thread.start()
_botaprint_thread.start()
logger.info('Service threads started.')

# ── Wait for readiness ─────────────────────────────────────────────────────────
def _wait_for(url: str, timeout: int = 45) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.35)
    return False

logger.info('Waiting for Django (up to 45 s)...')
if not _wait_for('http://127.0.0.1:8000/', timeout=45):
    _error(
        'BotaShop — Ошибка запуска',
        'Django не запустился в течение 45 секунд.\n'
        f'Журнал: {_LOGS_DIR / "launcher.log"}',
    )
    sys.exit(1)
logger.info('Django ready.')

logger.info('Waiting for BotaPrint (up to 25 s)...')
if not _wait_for('http://127.0.0.1:9100/health', timeout=25):
    logger.error('BotaPrint did not respond on port 9100.')
    _error(
        'BotaShop — BotaPrint не запустился',
        'BotaPrint не ответил на порту 9100 в течение 25 секунд.\n'
        f'Журнал: {_LOGS_DIR / "botaprint.log"}',
    )
    # Do not exit — Django still works, user can still add products
else:
    logger.info('BotaPrint ready.')

# ── Open browser ───────────────────────────────────────────────────────────────
_START_URL = 'http://127.0.0.1:8000/products/'
logger.info('Opening browser: %s', _START_URL)
webbrowser.open(_START_URL)

# ── Keep alive ─────────────────────────────────────────────────────────────────
logger.info('BotaShop is running. Both service threads are daemon — process lives until they die.')
try:
    _django_thread.join()
    _botaprint_thread.join()
except KeyboardInterrupt:
    logger.info('KeyboardInterrupt — shutting down.')
