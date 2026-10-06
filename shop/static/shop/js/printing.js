// BotaShop — shared print-UI helpers used by print_settings.html and
// direct_print.html. All requests go to same-origin Django endpoints
// (/api/health/, /api/printers/, and the print-submit endpoint) — the
// browser never talks to BotaPrint (127.0.0.1:9100) directly.

var BotaPrintUI = (function () {

  function csrfToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function setStatus(el, text, type) {
    if (!el) return;
    el.textContent = text;
    el.className = 'status-banner status-' + type;
  }

  function setMsg(el, text, type) {
    if (!el) return;
    if (!text) { el.style.display = 'none'; return; }
    el.textContent = text;
    el.className = 'print-msg msg-' + (type || 'info');
    el.style.display = 'block';
  }

  async function checkHealth(bannerEl) {
    setStatus(bannerEl, 'Проверка соединения с BotaPrint...', 'checking');
    try {
      const res = await fetch('/api/health/');
      const data = await res.json();
      if (data.ok) {
        setStatus(bannerEl, 'BotaPrint запущен и готов к работе', 'ok');
        return true;
      }
    } catch (e) { /* fall through */ }
    setStatus(bannerEl, 'BotaPrint не запущен. Запустите приложение печати и обновите страницу.', 'error');
    return false;
  }

  async function loadPrinters(selectEl, preselect) {
    selectEl.innerHTML = '<option value="">Загрузка...</option>';
    try {
      const res = await fetch('/api/printers/');
      const data = await res.json();

      if (data.error) {
        selectEl.innerHTML = '<option value="">' + escapeHtml(data.error) + '</option>';
        return;
      }
      const printers = data.printers || [];
      if (!printers.length) {
        selectEl.innerHTML = '<option value="">Принтеры не найдены</option>';
        return;
      }

      selectEl.innerHTML = '';
      let chosen = false;
      printers.forEach(function (p) {
        const opt = document.createElement('option');
        opt.value = p.name;
        opt.textContent = p.name + (p.is_default ? ' (по умолчанию)' : '');
        if (preselect && p.name === preselect) {
          opt.selected = true;
          chosen = true;
        } else if (!preselect && p.is_default && !chosen) {
          opt.selected = true;
          chosen = true;
        }
        selectEl.appendChild(opt);
      });
    } catch (e) {
      selectEl.innerHTML = '<option value="">Не удалось загрузить принтеры</option>';
    }
  }

  async function submitPrint(url, opts, msgEl, btnEl) {
    const printerName = opts.printerName;
    const paperSize = opts.paperSize;
    const copies = parseInt(opts.copies, 10);

    if (!printerName) {
      setMsg(msgEl, 'Выберите принтер из списка', 'error');
      return;
    }
    if (!copies || copies < 1 || copies > 100) {
      setMsg(msgEl, 'Введите количество копий от 1 до 100', 'error');
      return;
    }

    setMsg(msgEl, 'Отправка на печать...', 'info');
    if (btnEl) btnEl.disabled = true;

    try {
      const body = new URLSearchParams({
        printer_name: printerName,
        paper_size: paperSize,
        copies: String(copies),
        csrfmiddlewaretoken: csrfToken(),
      });
      const res = await fetch(url, { method: 'POST', body: body });
      const data = await res.json();
      setMsg(msgEl, data.message || (data.success ? 'Готово' : 'Ошибка'), data.success ? 'ok' : 'error');
    } catch (e) {
      setMsg(msgEl, 'Не удалось соединиться с сервером: ' + e.message, 'error');
    } finally {
      if (btnEl) btnEl.disabled = false;
    }
  }

  return {
    checkHealth: checkHealth,
    loadPrinters: loadPrinters,
    submitPrint: submitPrint,
    setStatus: setStatus,
    setMsg: setMsg,
  };
})();
