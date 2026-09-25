// Links, feed URLs, city panels and subscription help remain available without JS.
// With JS, show only the selected city and make the directory searchable.
(() => {
  const links = [...document.querySelectorAll('[data-city]')];
  const panels = [...document.querySelectorAll('[data-panel]')];
  const search = document.querySelector('#city-search');
  const directory = document.querySelector('#city-directory');
  const searchEmpty = document.querySelector('.search-empty');
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
      if (known.has(requested)) {
        if (directory) directory.open = false;
        panels.find(panel => panel.dataset.panel === code)?.scrollIntoView({ block: 'start' });
      }
    }
    window.addEventListener('hashchange', selectCity);
    selectCity();
    links.forEach(link => link.addEventListener('click', () => {
      if (location.hash === link.getAttribute('href')) selectCity();
    }));
    search?.addEventListener('focus', () => { if (directory) directory.open = true; });
    search?.addEventListener('input', () => {
      const normalize = value => value.toLowerCase().replace(/省|市|自治区|特别行政区/g, '');
      const query = normalize(search.value.trim());
      let visible = 0;
      for (const link of links) {
        link.hidden = !!query && !normalize(link.dataset.name).includes(query) && !link.dataset.city.includes(query);
        if (!link.hidden) visible++;
      }
      if (searchEmpty) searchEmpty.hidden = visible !== 0;
      if (directory) directory.open = true;
    });
  }
  document.querySelectorAll('[data-copy]').forEach(button => {
    button.addEventListener('click', async () => {
      const result = button.parentElement.querySelector('.copy-result');
      try {
        await navigator.clipboard.writeText(button.dataset.copy);
        result.textContent = '已复制。下一步：在日历应用中选择“通过 URL 订阅”并粘贴地址。';
      } catch {
        result.textContent = '无法自动复制，请长按或选中上方链接手动复制，再在日历中通过 URL 订阅。';
      }
    });
  });
})();
