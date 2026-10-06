"""
Thin integration layer between Django and the local BotaPrint agent.

Responsibilities kept here:
  - the single place that speaks HTTP to BotaPrint (no view duplicates this);
  - recording a PrintJob snapshot for every print attempt (success or failure).

Responsibilities deliberately NOT here (they stay in botaprint/):
  - printer enumeration internals, Pillow rendering, DEVMODE, Windows GDI.
"""

import json
import logging
import urllib.error
import urllib.request

from .models import PrintJob

logger = logging.getLogger(__name__)

BOTAPRINT_URL = 'http://127.0.0.1:9100'
_DEFAULT_TIMEOUT = 15


class BotaPrintError(Exception):
    """Raised when BotaPrint cannot be reached or returns an HTTP error."""


def _request(method: str, path: str, payload: dict | None = None, timeout: int = _DEFAULT_TIMEOUT) -> dict:
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(
        BOTAPRINT_URL + path,
        data=data,
        headers={'Content-Type': 'application/json'},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode('utf-8'))
            message = body.get('message') or body.get('error') or str(exc)
        except Exception:
            message = str(exc)
        raise BotaPrintError(message) from exc
    except urllib.error.URLError as exc:
        logger.warning('BotaPrint unreachable: %s', exc)
        raise BotaPrintError(
            'Не удалось соединиться с BotaPrint. Убедитесь, что BotaPrint запущен.'
        ) from exc


def check_health() -> bool:
    """True if BotaPrint responds and reports status ok."""
    try:
        data = _request('GET', '/health', timeout=3)
        return data.get('status') == 'ok'
    except BotaPrintError:
        return False


def get_printers() -> dict:
    """{'printers': [...]}  or  {'printers': [], 'error': '...'}"""
    try:
        return _request('GET', '/printers', timeout=5)
    except BotaPrintError as exc:
        return {'printers': [], 'error': str(exc)}


def print_label(*, printer_name, product_name, price, copies, paper_size, variant=None) -> PrintJob:
    """
    Send one print job to BotaPrint and persist a PrintJob record either way.

    Never raises — any failure (network, HTTP, or BotaPrint-reported) is
    captured on the returned PrintJob (status=FAILED, error_message set).
    """
    common = dict(
        variant=variant,
        product_name=product_name,
        price=price,
        printer_name=printer_name,
        label_size=paper_size,
        copies=copies,
    )
    try:
        result = _request('POST', '/print-label', {
            'printer_name': printer_name,
            'product_name': product_name,
            'price': float(price),
            'copies': copies,
            'paper_size': paper_size,
        })
    except BotaPrintError as exc:
        return PrintJob.objects.create(status=PrintJob.Status.FAILED, error_message=str(exc), **common)

    if result.get('success'):
        return PrintJob.objects.create(status=PrintJob.Status.SUCCESS, **common)

    message = result.get('message') or 'Неизвестная ошибка печати'
    return PrintJob.objects.create(status=PrintJob.Status.FAILED, error_message=message, **common)
