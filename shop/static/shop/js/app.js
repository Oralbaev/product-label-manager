// BotaShop — small shared UI behaviors (no framework, no build step).

document.addEventListener('DOMContentLoaded', function () {
  // Confirm destructive actions on forms marked with data-confirm="...".
  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!window.confirm(form.getAttribute('data-confirm'))) {
        e.preventDefault();
      }
    });
  });
});
