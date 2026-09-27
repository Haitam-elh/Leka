/* ==========================================================================
   LEKA, interactions
   Principe : un seul moment animé (l'analyse du produit), le reste est
   déclenché par l'utilisateur ou par le scroll, et toujours discret.
   ========================================================================== */
(() => {
  'use strict';

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduced) document.documentElement.classList.add('motion-ok');

  /* ---- 1. En-tête : filet au scroll -------------------------------------- */
  const header = document.getElementById('header');
  const onScrollHeader = () => header.classList.toggle('is-stuck', window.scrollY > 8);
  window.addEventListener('scroll', onScrollHeader, { passive: true });
  onScrollHeader();

  /* ---- 2. Menu mobile ----------------------------------------------------- */
  const burger = document.getElementById('burger');
  const nav = document.getElementById('nav');
  const MENU_LABELS = {
    fr: ['Fermer le menu', 'Ouvrir le menu'],
    en: ['Close menu', 'Open menu'],
    de: ['Menü schließen', 'Menü öffnen'],
    es: ['Cerrar menú', 'Abrir menú'],
    it: ['Chiudi menu', 'Apri menu'],
    nl: ['Menu sluiten', 'Menu openen'],
    pt: ['Fechar menu', 'Abrir menu']
  };
  const setNav = (open) => {
    document.body.classList.toggle('nav-open', open);
    burger.setAttribute('aria-expanded', String(open));
    const labels = MENU_LABELS[document.documentElement.lang] || MENU_LABELS.fr;
    burger.setAttribute('aria-label', open ? labels[0] : labels[1]);
  };
  burger.addEventListener('click', () => setNav(!document.body.classList.contains('nav-open')));
  nav.addEventListener('click', (e) => { if (e.target.tagName === 'A') setNav(false); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') setNav(false); });

  /* ---- 3. Révélations ----------------------------------------------------- */
  const reveals = document.querySelectorAll('.reveal');
  if (reduced || !('IntersectionObserver' in window)) {
    reveals.forEach((el) => el.classList.add('is-in'));
  } else {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        io.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
    reveals.forEach((el) => io.observe(el));
  }

  /* ---- 4. Le seul moment orchestré : l'analyse du produit ---------------- */
  const steps = [...document.querySelectorAll('#appSteps li')];
  const timer = document.getElementById('appTimer');
  if (steps.length) {
    if (reduced) {
      steps.forEach((li) => li.classList.add('is-done'));
      if (timer) timer.textContent = '24 s';
    } else {
      let i = 0;
      const tick = () => {
        if (i >= steps.length) return;
        steps[i].classList.add('is-done');
        if (timer) timer.textContent = `${Math.round(((i + 1) / steps.length) * 24)} s`;
        i += 1;
        setTimeout(tick, 420);
      };
      setTimeout(tick, 900);
    }
  }

  /* ---- 5. Le liseré violet sous les 4 étapes ----------------------------- */
  const flow = document.getElementById('flow');
  if (flow && !reduced && 'IntersectionObserver' in window) {
    const fio = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        flow.classList.add('is-live');
        fio.disconnect();
      });
    }, { threshold: 0.35 });
    fio.observe(flow);
  } else if (flow) {
    flow.classList.add('is-live');
  }

  /* ---- 6. Chronologie de l'incident, liée au scroll ---------------------- */
  const timeline = document.getElementById('timeline');
  const fill = document.getElementById('timelineFill');
  if (timeline) {
    const items = [...timeline.querySelectorAll('li')];
    if (reduced) {
      items.forEach((li) => li.classList.add('is-on'));
      if (fill) fill.style.height = '100%';
    } else {
      let ticking = false;
      const update = () => {
        ticking = false;
        const rect = timeline.getBoundingClientRect();
        const start = window.innerHeight * 0.82;
        const progress = Math.max(0, Math.min(1, (start - rect.top) / Math.max(1, rect.height * 0.85)));
        const reached = Math.floor(progress * items.length);
        items.forEach((li, index) => li.classList.toggle('is-on', index < reached));
        if (fill) fill.style.height = `${Math.min(100, progress * 100)}%`;
      };
      const request = () => {
        if (ticking) return;
        ticking = true;
        window.requestAnimationFrame(update);
      };
      window.addEventListener('scroll', request, { passive: true });
      window.addEventListener('resize', request, { passive: true });
      update();
    }
  }
})();
