"""
BotaPrint — локальный агент прямой печати этикеток для Windows.

Запуск:  python botaprint/main.py
API:     http://127.0.0.1:9100
Docs:    http://127.0.0.1:9100/docs

Архитектура:
  Django → BotaPrint → Windows GDI → принтер

SumatraPDF не используется.
PDF-файлы не используются.
Этикетка рендерится через Pillow и отправляется напрямую через win32ui.
"""

import io
import logging
import os
from decimal import Decimal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

try:
    from botaprint import printing   # when imported as a package (launcher, PyInstaller)
    from botaprint.paper_sizes import SUPPORTED_LABEL_SIZES, DEFAULT_LABEL_SIZE
except ImportError:
    import printing                  # when run standalone: python botaprint/main.py
    from paper_sizes import SUPPORTED_LABEL_SIZES, DEFAULT_LABEL_SIZE

logging.basicConfig(level=logging.INFO, format='%(levelname)s  %(name)s  %(message)s')
logger = logging.getLogger('botaprint')

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title='BotaPrint',
    version='2.0.0',
    description='Локальный агент прямой печати этикеток 43×25 мм для Windows',
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://127.0.0.1:8000', 'http://localhost:8000'],
    allow_methods=['GET', 'POST', 'OPTIONS'],
    allow_headers=['Content-Type', 'Accept'],
)

# ── Schemas ───────────────────────────────────────────────────────────────────


class PrintRequest(BaseModel):
    printer_name: str
    product_name: str
    price: float        # accepts JS number; int() conversion happens in printing.py
    copies: int = 1
    paper_size: str = DEFAULT_LABEL_SIZE


class PreviewRequest(BaseModel):
    product_name: str
    price: float
    dpi: int = 203      # preview resolution
    paper_size: str = DEFAULT_LABEL_SIZE


class DebugPrinterRequest(BaseModel):
    printer_name: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.get('/health')
def health():
    """Проверка состояния агента."""
    return {'status': 'ok', 'app': 'BotaPrint', 'version': '2.0.0'}


@app.get('/printers')
def get_printers():
    """Возвращает список установленных принтеров Windows."""
    printers = printing.list_printers()
    if not printers:
        try:
            import win32print  # noqa: F401
        except ImportError:
            return {
                'printers': [],
                'error': 'pywin32 не установлен. Выполните: pip install pywin32',
            }
    return {'printers': printers}


@app.get('/paper-sizes')
def get_paper_sizes():
    """Возвращает список поддерживаемых размеров этикеток."""
    return {
        'sizes': list(SUPPORTED_LABEL_SIZES.keys()),
        'default': DEFAULT_LABEL_SIZE,
        'details': SUPPORTED_LABEL_SIZES,
    }


@app.post('/print-label')
def print_label_endpoint(req: PrintRequest):
    """
    Рендерит этикетку 43×25 мм и отправляет её напрямую на выбранный принтер.

    Тело запроса:
        printer_name  — имя принтера из /printers
        product_name  — название товара
        price         — цена (целое или дробное число)
        copies        — количество копий (1–100)
    """
    # ── Ручная валидация с русскими сообщениями ───────────────────────────────
    if not req.printer_name.strip():
        return JSONResponse(
            status_code=400,
            content={'success': False, 'message': 'Укажите имя принтера'},
        )
    if not req.product_name.strip():
        return JSONResponse(
            status_code=400,
            content={'success': False, 'message': 'Введите название товара'},
        )
    if len(req.product_name) > 200:
        return JSONResponse(
            status_code=400,
            content={'success': False, 'message': 'Название товара слишком длинное (макс. 200 символов)'},
        )
    if req.price < 0:
        return JSONResponse(
            status_code=400,
            content={'success': False, 'message': 'Цена должна быть не меньше 0'},
        )
    if not (1 <= req.copies <= 100):
        return JSONResponse(
            status_code=400,
            content={'success': False, 'message': 'Количество копий должно быть от 1 до 100'},
        )

    # ── Печать ────────────────────────────────────────────────────────────────
    try:
        result = printing.print_label(
            printer_name=req.printer_name.strip(),
            product_name=req.product_name.strip(),
            price=req.price,
            copies=req.copies,
            paper_size=req.paper_size,
        )
        return {
            'success'         : True,
            'message'         : 'Этикетки отправлены на печать',
            'copies'          : result['copies'],
            'printer'         : result['printer'],
            'dpi_x'           : result.get('dpi_x'),
            'dpi_y'           : result.get('dpi_y'),
            'label_px'        : f"{result.get('label_w_px')}×{result.get('label_h_px')}",
            'dest_rect'       : result.get('dest_rect'),
            'custom_accepted' : result.get('custom_accepted'),
            'global_unchanged': result.get('global_unchanged'),
        }
    except RuntimeError as exc:
        msg = str(exc)
        status = 404 if 'не найден' in msg else 500
        logger.error('print_label failed: %s', exc)
        return JSONResponse(
            status_code=status,
            content={'success': False, 'message': msg},
        )
    except Exception as exc:
        logger.exception('Unexpected error in /print-label')
        return JSONResponse(
            status_code=500,
            content={'success': False, 'message': f'Внутренняя ошибка: {exc}'},
        )


@app.post('/debug-printer')
def debug_printer(req: DebugPrinterRequest):
    """
    Inspect a printer's device capabilities using the per-job 43×25 mm DEVMODE.

    Returns DPI, physical page size, printable area, offsets, and whether
    the driver accepted the custom 43×25 mm paper size.
    Use this to calibrate centering before a real print.
    """
    known = {p['name'] for p in printing.list_printers()}
    if req.printer_name not in known:
        return JSONResponse(
            status_code=404,
            content={'error': f'Принтер не найден: {req.printer_name}'},
        )
    try:
        caps = printing.get_printer_caps_with_job_devmode(req.printer_name)
        # Annotate with the requested label size for clarity
        caps['requested_label_width_mm']  = printing.LABEL_W_MM
        caps['requested_label_height_mm'] = printing.LABEL_H_MM
        dpi_x = caps.get('dpi_x', 203)
        dpi_y = caps.get('dpi_y', 203)
        caps['raster_width_px']  = round(printing.LABEL_W_MM / 25.4 * dpi_x)
        caps['raster_height_px'] = round(printing.LABEL_H_MM / 25.4 * dpi_y)
        return caps
    except Exception as exc:
        logger.exception('debug_printer failed for %r', req.printer_name)
        return JSONResponse(
            status_code=500,
            content={'error': str(exc)},
        )


@app.post('/preview-label', response_class=Response)
def preview_label(req: PreviewRequest):
    """
    Возвращает PNG-превью этикетки без отправки на принтер.

    Используется для проверки макета без физического принтера.

    Тело запроса:
        product_name  — название товара
        price         — цена
        dpi           — разрешение превью (по умолчанию 203)
    """
    if not req.product_name.strip():
        return JSONResponse(
            status_code=400,
            content={'error': 'product_name обязателен'},
        )

    size_key = req.paper_size if req.paper_size in SUPPORTED_LABEL_SIZES else DEFAULT_LABEL_SIZE
    dims  = SUPPORTED_LABEL_SIZES[size_key]
    dpi   = max(72, min(600, req.dpi))
    w_px  = round(dims['width_mm']  / 25.4 * dpi)
    h_px  = round(dims['height_mm'] / 25.4 * dpi)

    img = printing.render_label_image(
        req.product_name.strip(), req.price, w_px, h_px, dpi=dpi, paper_size=size_key
    )
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return Response(content=buf.read(), media_type='image/png')


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=9100, log_level='info')
