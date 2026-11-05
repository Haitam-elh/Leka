/* ==========================================================================
   LEKA, la page Tarifs (LEKA-431, LEKA-446)
   Aucun prix n'est ecrit ici : tout vient de GET /api/v1/pricing, calcule
   par le serveur a partir du catalogue (api/leka/billing/catalogue.yaml),
   tel que le paiement le facturera. Cette page ne fait qu'afficher, et
   compter ce que le visiteur choisit (POST /api/v1/pricing/events : quoi,
   sur quelle formule, jamais qui).
   Chaque carte dit ce que dit celle de la plateforme (Facturation >
   Formules) : les memes lignes, dans le meme ordre, avec les memes mots
   (e2e/pricing.spec.ts les compare).
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
      quoteSub: 'Utilisateurs et capacité adaptés',
      user: '{n} utilisateur',
      users: '{n} utilisateurs inclus',
      sources: '{n} sources connectées',
      analyses: '{n} analyses standard équivalentes / mois',
      credits: ' ({n} crédits IA)',
      alertRules: '{n} règles d\'alerte',
      alertRulesBasic: '{n} règles d\'alerte de base',
      workflows: '{n} workflows récurrents enregistrés',
      soon: 'bientôt',
      agents: '{n} agents spécialisés inclus',
      agentsEvery: 'Tous les agents spécialisés inclus',
      trial: 'Essai gratuit de {days} jours, carte requise',
      addOns: 'Les agents fondamentaux de LEKA sont inclus dans chaque formule, et les formules payantes incluent des agents spécialisés : {included}. Les autres s\'achètent à l\'unité, de {low} à {high} par mois selon leur niveau (Standard, Spécialisé, Expert), ou en bundle{saving}, à partir de la formule {minimum}. Leur travail consomme les crédits IA de votre formule.',
      addOnsPlan: '{n} avec {plan}',
      addOnsEvery: 'tous avec {plan}',
      addOnsSaving: ', jusqu\'à {percent} % moins cher',
      and: ', ',
      start: 'Commencer',
      startFree: 'Commencer gratuitement',
      book: 'Réserver un rendez-vous avec notre équipe',
      contact: 'Nous contacter',
      orWrite: 'ou nous écrire',
      launchNote: 'Offre de lancement : −{percent} % pendant {months} mois en facturation mensuelle.',
      launchTerms: 'Offre de lancement : −{percent} % sur les {months} premiers mois d\'un abonnement mensuel souscrit pendant l\'offre, puis le prix catalogue. Non cumulable avec la remise annuelle de {annual} %.',
      trialTerms: 'Essai Growth : {days} jours gratuits, carte bancaire requise, une fois par espace. À la fin de l\'essai, l\'abonnement démarre et la carte est débitée du prix affiché, puis à chaque échéance, sauf annulation avant la fin de l\'essai. Les abonnements se renouvellent automatiquement jusqu\'à résiliation.',
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
      quoteSub: 'Users and capacity tailored',
      user: '{n} user',
      users: '{n} users included',
      sources: '{n} connected sources',
      analyses: '{n} standard-equivalent analyses / month',
      credits: ' ({n} AI credits)',
      alertRules: '{n} alert rules',
      alertRulesBasic: '{n} basic alert rules',
      workflows: '{n} saved recurring workflows',
      soon: 'soon',
      agents: '{n} specialised agents included',
      agentsEvery: 'Every specialised agent included',
      trial: '{days}-day free trial, card required',
      addOns: 'LEKA\'s fundamental agents are included in every plan, and the paid plans include specialised agents: {included}. The others are bought on their own, from {low} to {high} a month by their level (Standard, Specialised, Expert), or in a bundle{saving}, from the {minimum} plan. Their work uses your plan\'s AI credits.',
      addOnsPlan: '{n} with {plan}',
      addOnsEvery: 'all of them with {plan}',
      addOnsSaving: ', up to {percent}% cheaper',
      and: ', ',
      start: 'Get started',
      startFree: 'Start for free',
      book: 'Book a meeting with our team',
      contact: 'Contact us',
      orWrite: 'or write to us',
      launchNote: 'Launch offer: −{percent}% for {months} months on monthly billing.',
      launchTerms: 'Launch offer: −{percent}% for the first {months} months of a monthly subscription taken during the offer, then the list price. Not combined with the {annual}% annual discount.',
      trialTerms: 'Growth trial: {days} free days, card required, once per workspace. When the trial ends, the subscription starts and the card is charged the price shown, then at each renewal, unless cancelled before the trial ends. Subscriptions renew automatically until cancelled.',
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
      box.appendChild(el('span', { class: 'plan__terms', text: t('quoteSub') }));
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

  const count = (n) => new Intl.NumberFormat(lang() === 'fr' ? 'fr-FR' : 'en-GB').format(n);

  /** What a plan holds, line by line, as the platform's card says it. */
  function lines(plan) {
    const q = plan.quotas;
    const found = [];
    const line = (text, extra = {}) => found.push({ text, ...extra });
    if (q.users) line(q.users > 1 ? t('users', { n: count(q.users) }) : t('user', { n: q.users }), { strong: true });
    if (q.sources) line(t('sources', { n: count(q.sources) }));
    if (q.analyses) {
      const credits = plan.ai_credits_per_month ? t('credits', { n: count(plan.ai_credits_per_month) }) : '';
      line(t('analyses', { n: count(q.analyses) }) + credits);
    }
    // Not built yet: said, never announced as working.
    if (q.alert_rules) line(t(plan.key === 'starter' ? 'alertRulesBasic' : 'alertRules', { n: count(q.alert_rules) }), { soon: true });
    if (q.workflows) line(t('workflows', { n: count(q.workflows) }), { soon: true });
    if (plan.agents_every) line(t('agentsEvery'));
    else if (plan.agents_included) line(t('agents', { n: count(plan.agents_included) }));
    plan.features.forEach((said) => line(words(said)));
    if (plan.trial_days) line(t('trial', { days: plan.trial_days }), { trial: true });
    return found;
  }

  function card(plan) {
    const features = lines(plan).map((f) => el('li', {
      class: [f.strong && 'plan__strong', f.trial && 'plan__trial'].filter(Boolean).join(' ') || null,
    }, [
      el('span', { text: f.text }),
      f.soon ? el('span', { class: 'plan__note', text: ` (${t('soon')})` }) : null,
    ]));
    const head = [el('h2', { class: 'plan__name', text: plan.name })];
    if (plan.recommended) head.push(el('span', { class: 'plan__badge', text: t('recommended') }));
    return el('article', { class: `plan${plan.recommended ? ' plan--recommended' : ''}`, 'data-plan': plan.key }, [
      el('div', { class: 'plan__head' }, head),
      el('p', { class: 'plan__tagline', text: words(plan.tagline) }),
      priceBlock(plan),
      cta(plan),
      el('ul', { class: 'plan__features' }, features),
      el('p', { class: 'plan__audience', text: words(plan.audience) }),
    ]);
  }

  /** The agents sold apart, summed up from the catalogue: what the platform's marketplace says. */
  function addOns(pricing) {
    const sold = pricing.add_ons;
    const box = $('addOnsText');
    if (!sold || sold.lowest_price === null) return;
    const included = pricing.plans
      .filter((plan) => plan.agents_included)
      .map((plan) => (plan.agents_every
        ? t('addOnsEvery', { plan: plan.name })
        : t('addOnsPlan', { n: count(plan.agents_included), plan: plan.name })))
      .join(t('and'));
    const minimum = (pricing.plans.find((plan) => plan.key === sold.minimum_plan) || { name: sold.minimum_plan }).name;
    box.textContent = t('addOns', {
      included,
      low: money(sold.lowest_price),
      high: money(sold.highest_price),
      saving: sold.best_saving_percent ? t('addOnsSaving', { percent: sold.best_saving_percent }) : '',
      minimum,
    });
  }

  function render() {
    const pricing = state.pricing;
    if (!pricing) return;
    const grid = $('plans');
    grid.replaceChildren(...pricing.plans.map(card));
    grid.setAttribute('aria-busy', 'false');
    $('annualSave').textContent = t('save', { percent: pricing.annual_discount_percent });
    addOns(pricing);
    const launch = pricing.launch_offer;
    const note = $('launchNote');
    note.hidden = !launch.open || state.interval !== 'month';
    note.textContent = t('launchNote', { percent: launch.percent, months: launch.months });
    const terms = $('launchTerms');
    terms.hidden = !launch.open;
    terms.textContent = t('launchTerms', { percent: launch.percent, months: launch.months, annual: pricing.annual_discount_percent });
    const trial = pricing.plans.find((plan) => plan.trial_days);
    $('trialTerms').hidden = !trial;
    if (trial) $('trialTerms').textContent = t('trialTerms', { days: trial.trial_days });
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
