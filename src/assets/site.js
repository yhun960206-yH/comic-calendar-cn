// Anchors remain usable without JavaScript; enhancement filters the two city panels.
(() => {
  const links = [...document.querySelectorAll('[data-city]')];
  const panels = [...document.querySelectorAll('[data-panel]')];
  if (links.length && panels.length) {
    function selectCity() {
      const code = location.hash.match(/^#city-(110100|310100)$/)?.[1] || '110100';
      for (const link of links) {
        if (link.dataset.city === code) link.setAttribute('aria-current', 'true');
        else link.removeAttribute('aria-current');
      }
      for (const panel of panels) panel.hidden = panel.dataset.panel !== code;
    }
    window.addEventListener('hashchange', selectCity);
    selectCity();
  }
  document.querySelectorAll('[data-copy]').forEach(button => {
    button.addEventListener('click', async () => {
      const result = button.parentElement.querySelector('.copy-result');
      try {
        await navigator.clipboard.writeText(button.dataset.copy);
        result.textContent = '已复制订阅链接';
      } catch {
        result.textContent = '无法自动复制，请长按或选中左侧链接手动复制';
      }
    });
  });
})();
