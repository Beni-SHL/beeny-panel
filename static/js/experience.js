(() => {
  'use strict';
  document.querySelectorAll('[data-toggle-password]').forEach(button => {
    button.addEventListener('click', () => {
      const field = document.getElementById(button.dataset.togglePassword);
      const visible = field.type === 'password';
      field.type = visible ? 'text' : 'password';
      button.textContent = visible ? button.dataset.hide : button.dataset.show;
      button.setAttribute('aria-pressed', String(visible));
    });
  });
  const dialog = document.getElementById('feedback-dialog');
  if (dialog) {
    const notices = [...document.querySelectorAll('main > .notice')];
    if (notices.length) {
      dialog.querySelector('p').textContent = notices.map(n => n.textContent).join('\n');
      if (notices.some(n => n.classList.contains('error') || n.classList.contains('warning'))) dialog.querySelector('.feedback-mark').textContent = '!';
      dialog.showModal();
      notices.forEach(n => n.hidden = true);
    }
    dialog.querySelector('button').addEventListener('click', () => dialog.close());
  }
  document.querySelectorAll('[data-copy-card]').forEach(button => button.addEventListener('click', async () => {
    const initial = button.textContent;
    try { await navigator.clipboard.writeText(button.dataset.copyCard); button.textContent = 'شماره کارت کپی شد ✓'; }
    catch (_) { button.textContent = button.dataset.copyCard; }
    setTimeout(() => button.textContent = initial, 2500);
  }));
  document.querySelectorAll('[data-confirm-delete]').forEach(form => form.addEventListener('submit', event => {
    if (!window.confirm('Delete this request and permanently remove its receipt image?')) event.preventDefault();
  }));
  document.querySelectorAll('[data-notifications]').forEach(center => {
    const bell = center.querySelector('.notification-bell'), popup = center.querySelector('.notification-popover');
    const items = center.querySelector('.notification-items'), badge = center.querySelector('.notification-badge');
    const fa = center.dataset.locale === 'fa';
    let upto = 0, loading = false;
    async function refresh() {
      if (loading) return;
      loading = true;
      try {
        const response = await fetch(center.dataset.notifications, {headers:{Accept:'application/json'}, cache:'no-store'});
        if (!response.ok || response.redirected || !response.headers.get('content-type')?.includes('application/json')) return;
        const data = await response.json();
        upto = data.latest_id;
        badge.textContent = data.unread > 99 ? '99+' : String(data.unread);
        badge.hidden = !data.unread;
        items.replaceChildren();
        if (!data.items.length) { const p = document.createElement('p'); p.textContent = fa ? 'هنوز اعلانی ندارید.' : 'No notifications yet.'; items.append(p); }
        data.items.forEach(row => {
          const article = document.createElement('article'), title = document.createElement('b'), body = document.createElement('p'), stamp = document.createElement('time');
          title.textContent = row.title; body.textContent = row.body; stamp.textContent = new Date(row.created).toLocaleString(fa ? 'fa-IR' : 'en-GB');
          article.append(title, body, stamp); items.append(article);
        });
      } catch (_) { /* Leave current messages readable while offline. */ }
      finally { loading = false; }
    }
    bell.addEventListener('click', () => {popup.hidden = !popup.hidden; bell.setAttribute('aria-expanded', String(!popup.hidden)); if (!popup.hidden) refresh();});
    document.addEventListener('click', event => { if (!center.contains(event.target)) {popup.hidden = true; bell.setAttribute('aria-expanded','false');} });
    center.addEventListener('keydown', event => {if (event.key === 'Escape') {popup.hidden=true; bell.focus(); bell.setAttribute('aria-expanded','false');}});
    center.querySelector('.notification-read').addEventListener('click', async () => {
      try {const response = await fetch(center.dataset.notifications+'/read', {method:'POST', body:new URLSearchParams({csrf:center.dataset.csrf, upto:String(upto)})}); if (response.ok && !response.redirected) await refresh();} catch (_) {}
    });
    refresh(); setInterval(() => {if (!document.hidden) refresh();},60000);
  });
  const addCard = document.getElementById('add-bank-card'), cards = document.getElementById('extra-cards');
  if (addCard && cards) {
    cards.addEventListener('click', event => {if (event.target.matches('[data-remove-card]')) event.target.closest('.extra-card').remove();});
    addCard.addEventListener('click', () => {
      if (cards.children.length >= 7) return;
      const card = document.createElement('div'); card.className = 'extra-card admin-plan';
      ['Bank name','Card holder','Card number'].forEach((label,i) => {
        const wrapper = document.createElement('label'), input = document.createElement('input'); wrapper.textContent=label;
        input.name=['extra_bank_name','extra_card_holder','extra_card_number'][i]; input.maxLength=i===2?24:100;
        if (i===2) input.inputMode='numeric'; wrapper.append(input); card.append(wrapper);
      });
      const label = document.createElement('label'), select = document.createElement('select'); label.textContent='Color';select.name='extra_card_color';
      ['violet','blue','emerald','sunset','rose','midnight'].forEach(color => {const option=document.createElement('option');option.value=color;option.textContent=color;select.append(option);});label.append(select);card.append(label);
      const remove=document.createElement('button');remove.type='button';remove.className='admin-button danger';remove.dataset.removeCard='';remove.textContent='Remove card';card.append(remove);cards.append(card);
      card.querySelector('input').focus();
    });
  }
})();
