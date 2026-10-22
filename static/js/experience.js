(() => {
  'use strict';
  function init(){
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
    try { await navigator.clipboard.writeText(button.dataset.copyCard); button.textContent = (document.documentElement.lang==='en'?"Card number copied \u2713":'شماره کارت کپی شد ✓'); }
    catch (_) {
      const field=document.createElement('textarea');field.value=button.dataset.copyCard;field.style.position='fixed';field.style.opacity='0';document.body.append(field);field.select();
      const copied=document.execCommand('copy');field.remove();button.textContent=copied?(document.documentElement.lang==='en'?"Card number copied \u2713":'شماره کارت کپی شد ✓'):button.dataset.copyCard;
    }
    setTimeout(() => button.textContent = initial, 2500);
  }));
  if(!window.beenyDeleteConfirmation){
    window.beenyDeleteConfirmation=true;
    document.addEventListener('submit',event=>{
      const form=event.target;
      if(!form.matches('[data-confirm-delete]'))return;
      const message=form.dataset.confirmDelete||'Delete this item permanently?';
      if(!window.confirm(window.adminT?.(message)||message))event.preventDefault();
    },true);
  }
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
  }
  init();document.addEventListener('admin:content-ready',init);
})();
