(() => {
  document.querySelectorAll('.flag[data-code]').forEach(el => {
    const code = el.dataset.code.toLowerCase();
    if (!/^[a-z]{2}$/.test(code)) return;
    const image = new Image();
    image.src = '/static/flags/'+code+'.svg';
    image.alt = code.toUpperCase();
    image.width = 28;image.height = 21;
    image.style.cssText = 'width:28px;height:21px;object-fit:cover;border-radius:4px;vertical-align:middle';
    image.onload = () => el.replaceChildren(image);
    image.onerror = () => {el.textContent=code.toUpperCase();};
  });
})();
