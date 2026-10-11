/* ==========================================================================
   LEKA, la page Tarifs (LEKA-431)
   Aucun prix n'est ecrit ici : tout vient de GET /api/v1/pricing, calcule
   par le serveur a partir du catalogue (api/leka/billing/catalogue.yaml),
   tel que le paiement le facturera. Cette page ne fait qu'afficher, et
   compter ce que le visiteur choisit (POST /api/v1/pricing/events : quoi,
   sur quelle formule, jamais qui).
   ========================================================================== */
(() => {
  'use strict';

  // L'API du site : api.<domaine> en ligne, le port 8000 en local.
  const host = window.location.hostname;
  const API = (host === 'localhost' || host === '127.0.0.1')
    ? `http://${host}:8000/api/v1`
    : `https://api.${host.replace(/^www\./, '')}/api/v1`;

  const T = {
    fr: {
      perMonth: '/ mois HT',
      list: 'au lieu de {price}',
      launch: 'pendant {months} mois, puis {price} / mois',
      yearly: 'facturé {price} / an HT',
      free: 'Gratuit',
      quote: 'Sur devis',
      recommended: 'Recommandé',
      credits: '{n} crédits IA / mois',
      creditsContract: 'Capacité IA définie au contrat',
      provisional: 'valeur de lancement',
      core: '{agents} inclus',
      managed: 'Modèle de langage géré par LEKA',
      ownLlm: 'Connexion de votre propre modèle de langage',
      anyTime: 'Capacité IA supplémentaire à tout moment',
      start: 'Commencer',
      startFree: 'Commencer gratuitement',
      book: 'Réserver un rendez-vous avec notre équipe',
      contact: 'Nous contacter',
      orWrite: 'ou nous écrire',
      launchNote: 'Offre de lancement : −{percent} % pendant {months} mois en facturation mensuelle.',
      launchTerms: 'Offre de lancement : −{percent} % sur les {months} premiers mois d\'un abonnement mensuel souscrit pendant l\'offre, puis le prix catalogue. Non cumulable avec la remise annuelle de {annual} %.',
      save: '−{percent} %',
    },
    en: {
      perMonth: '/ month excl. VAT',
      list: 'instead of {price}',
      launch: 'for {months} months, then {price} / month',
      yearly: 'billed {price} / year excl. VAT',
      free: 'Free',
      quote: 'Custom pricing',
      recommended: 'Recommended',
      credits: '{n} AI credits / month',
      creditsContract: 'AI capacity set by contract',
      provisional: 'launch value',
      core: '{agents} included',
      managed: 'Language model managed by LEKA',
      ownLlm: 'Connect your own language model',
      anyTime: 'Extra AI capacity at any time',
      start: 'Get started',
      startFree: 'Start for free',
      book: 'Book a meeting with our team',
      contact: 'Contact us',
      orWrite: 'or write to us',
      launchNote: 'Launch offer: −{percent}% for {months} months on monthly billing.',
      launchTerms: 'Launch offer: −{percent}% for the first {months} months of a monthly subscription taken during the offer, then the list price. Not combined with the {annual}% annual discount.',
      save: '−{percent}%',
    },
  };

  const state = { pricing: null, interval: 'month' };
  const $ = (id) => document.getElementById(id);
  const lang = () => (document.documentElement.lang === 'fr' ? 'fr' : 'en');
  const t = (key, values = {}) =>
    T[lang()][key].replace(/\{(\w+)\}/g, (_, name) => (values[name] !== undefined ? values[name] : ''));
  const words = (said) => said[lang()] || said.fr;

  function money(cents) {
    const whole = cents % 100 === 0;
    return new Intl.NumberFormat(lang() === 'fr' ? 'fr-FR' : 'en-GB', {
      style: 'currency',
      currency: (state.pricing && state.pricing.currency) || 'EUR',
      minimumFractionDigits: whole ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(cents / 100);
  }

  function track(event, extra = {}) {
    try {
      fetch(`${API}/pricing/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event, page: 'pricing', language: lang(), ...extra }),
        credentials: 'omit',
        keepalive: true,
      }).catch(() => {});
    } catch (e) { /* analytics never block a visitor */ }
  }

  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    Object.entries(attrs).forEach(([name, value]) => {
      if (name === 'text') node.textContent = value;
      else if (value !== null && value !== undefined) node.setAttribute(name, value);
    });
    children.forEach((child) => child && node.appendChild(child));
    return node;
  }

  function priceBlock(plan) {
    const box = el('div', { class: 'plan__price' });
    if (!plan.quotes.length) {
      box.appendChild(el('span', { class: 'plan__amount', text: t('quote') }));
      return box;
    }
    const quote = plan.quotes.find((q) => q.interval === state.interval) || plan.quotes[0];
    if (quote.list_monthly === 0) {
      box.appendChild(el('span', { class: 'plan__amount', text: t('free') }));
      return box;
    }
    box.appendChild(el('span', { class: 'plan__amount', text: money(quote.monthly) }));
    box.appendChild(el('span', { class: 'plan__per', text: ` ${t('perMonth')}` }));
    if (quote.discount) {
      box.appendChild(el('s', { class: 'plan__list', text: t('list', { price: money(quote.list_monthly) }) }));
    }
    if (quote.discount === 'launch') {
      box.appendChild(el('span', { class: 'plan__terms', text: t('launch', { months: quote.for_months, price: money(quote.then_monthly) }) }));
    } else if (quote.interval === 'year') {
      box.appendChild(el('span', { class: 'plan__terms', text: t('yearly', { price: money(quote.charged) }) }));
    }
    return box;
  }

  function cta(plan) {
    const pricing = state.pricing;
    const wrap = el('div', { class: 'plan__cta' });
    if (plan.self_service) {
      const href = `/register?plan=${encodeURIComponent(plan.key)}&interval=${encodeURIComponent(state.interval)}`;
      const link = el('a', {
        class: `btn ${plan.recommended ? 'btn--primary' : 'btn--ghost'}`,
        href,
        text: plan.key === 'free' ? t('startFree') : t('start'),
      });
      link.addEventListener('click', () => {
        track('plan_selected', { plan: plan.key, interval: state.interval });
        track('cta_clicked', { plan: plan.key, interval: state.interval });
      });
      wrap.appendChild(link);
      return wrap;
    }
    // Enterprise: a meeting with the team when a booking page is set, the
    // contact form always.
    const contact = pricing.booking.contact_url;
    if (pricing.booking.url) {
      const book = el('a', { class: 'btn btn--primary', href: pricing.booking.url, target: '_blank', rel: 'noopener', text: t('book') });
      book.addEventListener('click', () => track('enterprise_booking_clicked', { plan: plan.key }));
      wrap.appendChild(book);
      const write = el('a', { class: 'plan__alt', href: contact, text: t('orWrite') });
      write.addEventListener('click', () => track('enterprise_contact_clicked', { plan: plan.key }));
      wrap.appendChild(write);
    } else {
      const write = el('a', { class: 'btn btn--primary', href: contact, text: t('contact') });
      write.addEventListener('click', () => track('enterprise_contact_clicked', { plan: plan.key }));
      wrap.appendChild(write);
    }
    return wrap;
  }

  function card(plan) {
    const pricing = state.pricing;
    const agents = pricing.core_agents.map((a) => words(a.name)).join(lang() === 'fr' ? ' et ' : ' and ');
    const credits = plan.ai_credits_contractual
      ? t('creditsContract')
      : t('credits', { n: new Intl.NumberFormat(lang() === 'fr' ? 'fr-FR' : 'en-GB').format(plan.ai_credits_per_month) });
    const features = [
      el('li', {}, [
        el('span', { text: credits }),
        plan.ai_credits_provisional ? el('span', { class: 'plan__note', text: ` (${t('provisional')})` }) : null,
      ]),
      el('li', { text: t('core', { agents }) }),
      el('li', { text: plan.own_llm ? t('ownLlm') : t('managed') }),
      pricing.capacity_any_time ? el('li', { text: t('anyTime') }) : null,
    ];
    const head = [el('h2', { class: 'plan__name', text: plan.name })];
    if (plan.recommended) head.push(el('span', { class: 'plan__badge', text: t('recommended') }));
    return el('article', { class: `plan${plan.recommended ? ' plan--recommended' : ''}`, 'data-plan': plan.key }, [
      el('div', { class: 'plan__head' }, head),
      el('p', { class: 'plan__audience', text: words(plan.audience) }),
      priceBlock(plan),
      cta(plan),
      el('p', { class: 'plan__value', text: words(plan.value) }),
      el('ul', { class: 'plan__features' }, features),
    ]);
  }

  function render() {
    const pricing = state.pricing;
    if (!pricing) return;
    const grid = $('plans');
    grid.replaceChildren(...pricing.plans.map(card));
    grid.setAttribute('aria-busy', 'false');
    $('annualSave').textContent = t('save', { percent: pricing.annual_discount_percent });
    const launch = pricing.launch_offer;
    const note = $('launchNote');
    note.hidden = !launch.open || state.interval !== 'month';
    note.textContent = t('launchNote', { percent: launch.percent, months: launch.months });
    const terms = $('launchTerms');
    terms.hidden = !launch.open;
    terms.textContent = t('launchTerms', { percent: launch.percent, months: launch.months, annual: pricing.annual_discount_percent });
    document.querySelectorAll('.pricing-toggle [data-interval]').forEach((button) => {
      button.setAttribute('aria-checked', String(button.dataset.interval === state.interval));
    });
  }

  function choose(interval) {
    if (interval === state.interval) return;
    state.interval = interval;
    track('interval_selected', { interval });
    render();
  }

  function init() {
    document.querySelectorAll('.pricing-toggle [data-interval]').forEach((button) => {
      button.addEventListener('click', () => choose(button.dataset.interval));
      button.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
          event.preventDefault();
          const next = state.interval === 'month' ? 'year' : 'month';
          choose(next);
          document.querySelector(`.pricing-toggle [data-interval="${next}"]`).focus();
        }
      });
    });
    document.addEventListener('leka:langchange', render);
    fetch(`${API}/pricing`, { credentials: 'omit' })
      .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
      .then((pricing) => {
        state.pricing = pricing;
        render();
        track('page_viewed');
      })
      .catch(() => {
        $('pricingLoading').hidden = true;
        $('plans').setAttribute('aria-busy', 'false');
        $('pricingError').hidden = false;
      });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
