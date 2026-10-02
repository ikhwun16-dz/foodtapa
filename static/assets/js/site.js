(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  // header shadow
  const hdr = $('[data-hdr]');
  const onScroll = () => hdr && hdr.classList.toggle('is-scrolled', scrollY > 8);
  addEventListener('scroll', onScroll, { passive: true }); onScroll();

  // mobile menu
  const burger = $('[data-burger]'), nav = $('[data-nav]');
  burger && burger.addEventListener('click', () => {
    const open = burger.getAttribute('aria-expanded') !== 'true';
    burger.setAttribute('aria-expanded', open); nav.classList.toggle('is-open', open);
  });

  // carousels
  $$('[data-car]').forEach(track => {
    const id = track.dataset.car;
    const items = [...track.children];
    const step = () => (items[0] ? items[0].getBoundingClientRect().width + parseFloat(getComputedStyle(track).columnGap || getComputedStyle(track).gap || 0) : track.clientWidth);
    const go = dir => {
      const max = track.scrollWidth - track.clientWidth - 4;
      if (dir > 0 && track.scrollLeft >= max) track.scrollTo({ left: 0 });
      else if (dir < 0 && track.scrollLeft <= 4) track.scrollTo({ left: max });
      else track.scrollBy({ left: dir * step() });
    };
    $$(`[data-car-prev="${id}"]`).forEach(b => b.addEventListener('click', () => { stop(); go(-1); }));
    $$(`[data-car-next="${id}"]`).forEach(b => b.addEventListener('click', () => { stop(); go(1); }));
    const dotsEl = $(`[data-car-dots="${id}"]`);
    let dots = [];
    if (dotsEl) {
      dots = items.map((_, i) => {
        const b = document.createElement('button');
        b.type = 'button'; b.setAttribute('aria-label', `${i + 1}번 슬라이드`);
        b.addEventListener('click', () => { stop(); track.scrollTo({ left: i * track.clientWidth }); });
        dotsEl.appendChild(b); return b;
      });
      const sync = () => {
        const i = Math.round(track.scrollLeft / track.clientWidth);
        dots.forEach((d, j) => d.setAttribute('aria-current', i === j));
      };
      track.addEventListener('scroll', () => requestAnimationFrame(sync), { passive: true }); sync();
    }
    let timer = null;
    const ms = +track.dataset.autoplay;
    const stop = () => { clearInterval(timer); timer = null; };
    if (ms && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      timer = setInterval(() => document.visibilityState === 'visible' && go(1), ms);
      ['pointerdown', 'wheel', 'touchstart', 'focusin'].forEach(ev => track.addEventListener(ev, stop, { passive: true, once: true }));
    }
  });

  // color swatches
  const stage = $('[data-swatch-stage]');
  $$('[data-swatch]').forEach(b => b.addEventListener('click', () => {
    $$('[data-swatch]').forEach(x => x.setAttribute('aria-checked', x === b));
    const im = $('[data-swatch-img]'); if (im && b.dataset.img) im.src = b.dataset.img;
    $('[data-swatch-name]').textContent = b.dataset.name;
  }));

  // buy quiz
  $$('[data-pick]').forEach(b => b.addEventListener('click', () => {
    $$('[data-pick]').forEach(x => x.setAttribute('aria-pressed', x === b));
    $$('.plan').forEach(p => p.classList.remove('is-picked'));
    const t = $('#plan-' + b.dataset.pick);
    if (t) { t.classList.add('is-picked'); t.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' }); }
  }));

  // faq filter
  const ff = $('[data-faq-filter]');
  ff && ff.addEventListener('input', () => {
    const q = ff.value.trim();
    $$('.faq__item').forEach(d => {
      const hit = !q || d.textContent.includes(q);
      d.hidden = !hit; if (q && hit) d.open = true;
    });
  });

  // reading progress + toc
  const bar = $('[data-progress]');
  if (bar) {
    const body = $('.post__body');
    const links = $$('.toc a');
    const heads = links.map(a => document.getElementById(decodeURIComponent(a.hash.slice(1)))).filter(Boolean);
    addEventListener('scroll', () => {
      const r = body.getBoundingClientRect();
      bar.style.width = Math.min(100, Math.max(0, (-r.top / (r.height - innerHeight)) * 100)) + '%';
      let cur = 0; heads.forEach((h, i) => { if (h.getBoundingClientRect().top < 140) cur = i; });
      links.forEach((a, i) => a.classList.toggle('is-on', i === cur));
    }, { passive: true });
  }

  // share
  $$('[data-share]').forEach(b => b.addEventListener('click', async () => {
    const data = { title: document.title, url: location.href };
    try {
      if (navigator.share) await navigator.share(data);
      else { await navigator.clipboard.writeText(location.href); b.textContent = '링크 복사됨'; }
    } catch (e) { /* 사용자가 취소 */ }
  }));

  // 외부 링크 클릭 추적 (GA4 / 네이버 애널리틱스 연결 시 자동 사용)
  $$('[data-track]').forEach(a => a.addEventListener('click', () => {
    const ev = a.dataset.track;
    if (window.gtag) gtag('event', 'cta_click', { label: ev });
    if (window.wcs && window.wcs.event) try { wcs.event('cta', ev); } catch (e) {}
  }));
})();
