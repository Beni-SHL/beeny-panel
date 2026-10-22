(() => {
  'use strict';
  document.addEventListener('invalid',event=>{let el=event.target.parentElement;while(el){if(el.tagName==='DETAILS')el.open=true;el=el.parentElement;}},true);
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-';
  document.querySelectorAll('[data-password-controls]').forEach(controls => {
    const field = document.getElementById(controls.dataset.passwordControls);
    if (!field) return;
    const status = controls.querySelector('[data-password-status]');
    const toggle = controls.closest('.ac-field').querySelector('[data-profile-password-toggle]') || controls.querySelector('[data-password-toggle]');
    if(!toggle || controls.dataset.passwordBound)return;controls.dataset.passwordBound='1';
    controls.querySelector('[data-password-generate]').addEventListener('click', () => {
      if (!window.crypto || !window.crypto.getRandomValues) {
        status.textContent = 'Secure generation unavailable; enter a password manually.';
        return;
      }
      const bytes = window.crypto.getRandomValues(new Uint8Array(20));
      field.value = Array.from(bytes, byte => alphabet[byte & 63]).join('');
      field.type = 'text';
      toggle.setAttribute('aria-label', 'Hide');toggle.title=toggle.getAttribute('aria-label');
      toggle.setAttribute('aria-pressed', 'true');
      field.dispatchEvent(new Event('input', {bubbles: true}));
      status.textContent = 'Generated. Copy and share privately before saving.';
    });
    toggle.addEventListener('click', () => {
      field.type = field.type === 'password' ? 'text' : 'password';
      toggle.setAttribute('aria-label', field.type === 'text' ? 'Hide' : 'Show');toggle.title=toggle.getAttribute('aria-label');
      toggle.setAttribute('aria-pressed', String(field.type === 'text'));
    });
    controls.querySelector('[data-password-copy]').addEventListener('click', async () => {
      if (!field.value) { status.textContent = 'Enter or generate a password first.'; return; }
      try {
        await navigator.clipboard.writeText(field.value);
        status.textContent = 'Password copied.';
      } catch (_) {
        field.type = 'text'; toggle.setAttribute('aria-label', 'Hide');toggle.title=toggle.getAttribute('aria-label'); toggle.setAttribute('aria-pressed', 'true');
        field.focus(); field.select();
        status.textContent = 'Select and copy the password manually.';
      }
    });
  });
})();
