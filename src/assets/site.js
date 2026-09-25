// All city anchors work without JavaScript; enhance filtering and panel selection.
(() => {
  const links = [...document.querySelectorAll('[data-city]')];
  const panels = [...document.querySelectorAll('[data-panel]')];
  const search = document.querySelector('#city-search');
  if (links.length && panels.length) {
    const known = new Set(links.map(link => link.dataset.city));
    function selectCity() {
      const requested = location.hash.match(/^#city-(\d{6})$/)?.[1];
      const firstPopulated = links.find(link => Number(link.dataset.count) > 0)?.dataset.city;
      const code = known.has(requested) ? requested : (firstPopulated || (known.has('110100') ? '110100' : links[0].dataset.city));
      for (const link of links) {
        if (link.dataset.city === code) link.setAttribute('aria-current', 'true');
        else link.removeAttribute('aria-current');
      }
      for (const panel of panels) panel.hidden = panel.dataset.panel !== code;
    }
    window.addEventListener('hashchange', selectCity);
    selectCity();
    search?.addEventListener('input', () => {
      const query = search.value.trim().toLowerCase();
      for (const link of links) {
        link.hidden = !!query && !link.dataset.name.toLowerCase().includes(query) && !link.dataset.city.includes(query);
      }
    });
  }
  document.querySelectorAll('[data-copy]').forEach(button => {
    button.addEventListener('click', async () => {
      const result = button.parentElement.querySelector('.copy-result');
      try {
        await navigator.clipboard.writeText(button.dataset.copy);
        result.textContent = '已复制订阅链接';
      } catch {
        result.textContent = '无法自动复制，请长按或选中链接手动复制';
      }
    });
  });
})();
