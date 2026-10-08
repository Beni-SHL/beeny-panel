(() => {
  'use strict';
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-';
  document.querySelectorAll('[data-password-controls]').forEach(controls => {
    const field = document.getElementById(controls.dataset.passwordControls);
    if (!field) return;
    const status = controls.querySelector('[data-password-status]');
    const toggle = controls.querySelector('[data-password-toggle]');
    controls.querySelector('[data-password-generate]').addEventListener('click', () => {
      if (!window.crypto || !window.crypto.getRandomValues) {
        status.textContent = 'Secure generation unavailable; enter a password manually.';
        return;
      }
      const bytes = window.crypto.getRandomValues(new Uint8Array(20));
      field.value = Array.from(bytes, byte => alphabet[byte & 63]).join('');
      field.type = 'text';
      toggle.textContent = 'Hide';
      toggle.setAttribute('aria-pressed', 'true');
      field.dispatchEvent(new Event('input', {bubbles: true}));
      status.textContent = 'Generated. Copy and share privately before saving.';
    });
    toggle.addEventListener('click', () => {
      field.type = field.type === 'password' ? 'text' : 'password';
      toggle.textContent = field.type === 'text' ? 'Hide' : 'Show';
      toggle.setAttribute('aria-pressed', String(field.type === 'text'));
    });
    controls.querySelector('[data-password-copy]').addEventListener('click', async () => {
      if (!field.value) { status.textContent = 'Enter or generate a password first.'; return; }
      try {
        await navigator.clipboard.writeText(field.value);
        status.textContent = 'Password copied.';
      } catch (_) {
        field.type = 'text'; toggle.textContent = 'Hide'; toggle.setAttribute('aria-pressed', 'true');
        field.focus(); field.select();
        status.textContent = 'Select and copy the password manually.';
      }
    });
  });
})();
