/* LEKA, traductions des nouvelles pages (index, à propos, FAQ).
   Le français reste dans le HTML ; chaque langue ajoute un dictionnaire "texte FR" -> "texte traduit".
   Pour ajouter une langue : ajouter D.de = {...} etc. Une phrase absente reste en français. */
(() => {
  const D = { en: {
"Environnement":"Environment","Capacités":"Capabilities","De l'intention à l'action":"From intent to action","Contrôle":"Control","Se connecter":"Sign in","Découvrir LEKA":"Discover LEKA",
"Le système nerveux technologique de votre entreprise":"The technological nervous system of your company",
"Comprenez. Décidez. Agissez. Sans perdre de temps.":"Understand. Decide. Act. Without wasting time.",
"LEKA comprend votre environnement technologique, ses relations et ses capacités pour vous permettre d'aller directement du besoin à l'action.":"LEKA understands your technology environment, its relationships and its capabilities so you can go straight from need to action.",
"Voir comment ça fonctionne":"See how it works","Problème détecté · Facturation":"Issue detected · Billing","Des clients ne reçoivent plus leurs factures depuis 14:32.":"Customers have stopped receiving their invoices since 14:32.",
"Analyse dans le contexte de votre entreprise":"Analysis in the context of your company","Derniers déploiements":"Latest deployments","Métriques":"Metrics","Incidents récents":"Recent incidents","Graphe de dépendances":"Dependency graph",
"Cause probable identifiée":"Probable cause identified","Le problème est apparu après une modification du service d'envoi des factures, déployée aujourd'hui.":"The problem appeared after a change to the invoice-sending service, deployed today.",
"factures concernées":"invoices affected","détecté à":"detected at","Élevé":"High","risque client":"customer risk","Revoir la vidéo":"Watch again",
"Une nouvelle façon de faire":"A new way of working","Ne cherchez plus comment faire. Dites ce que vous voulez faire.":"Stop looking for how. Say what you want to do.",
"Vous n'avez plus besoin de connaître le bon outil, le bon service ou le bon chemin. Formulez simplement ce que vous voulez obtenir. LEKA comprend votre intention et détermine ce qu'il faut mobiliser pour y répondre.":"You no longer need to know the right tool, the right service or the right path. Simply state what you want to achieve. LEKA understands your intent and determines what to mobilize to deliver it.",
"Analyser un incident":"Analyze an incident","Comprendre l'impact d'un changement":"Understand the impact of a change","Vérifier la conformité d'un service":"Check a service for compliance","Préparer une migration":"Prepare a migration",
"Vous exprimez le besoin. LEKA trouve le chemin.":"You state the need. LEKA finds the way.",
"Voyez votre technologie comme un seul système.":"See your technology as a single system.",
"LEKA connecte les éléments qui composent votre environnement et révèle leurs relations : applications, services, bases de données, APIs, infrastructure, code, données, services externes.":"LEKA connects the elements that make up your environment and reveals their relationships: applications, services, databases, APIs, infrastructure, code, data, external services.",
"ce qui existe":"what exists","ce qui dépend de quoi":"what depends on what","ce qui change":"what changes","ce qui est impacté":"what is impacted","ce qui mérite votre attention":"what deserves your attention",
"Plus besoin de reconstruire le contexte. Il est déjà là.":"No need to rebuild the context. It is already there.","Changement":"Change","Impacté":"Impacted",
"Application web":"Web app","Base clients":"Customer database","Service facturation":"Billing service","Envoi factures":"Invoice sending","Paiement (externe)":"Payment (external)",
"Une capacité à la demande":"Capability on demand","Votre équipe technologique. À la demande.":"Your technology team. On demand.",
"Vous n'avez pas besoin de mobiliser un expert pour chaque question, analyse ou problème.":"You don't need to mobilize an expert for every question, analysis or problem.",
"Architecte":"Architect","Développeur":"Developer","Sécurité":"Security",
"Comprendre une architecture et ses dépendances.":"Understand an architecture and its dependencies.","Analyser incidents, infrastructure et performances.":"Analyze incidents, infrastructure and performance.","Analyser le code et préparer une modification.":"Analyze code and prepare a change.","Identifier les risques et proposer des corrections.":"Identify risks and propose fixes.","Analyser l'infrastructure et ses évolutions.":"Analyze the infrastructure and how it evolves.","Comprendre les données et leurs flux.":"Understand data and its flows.",
"La capacité dont vous avez besoin, au moment où vous en avez besoin.":"The capability you need, when you need it.","LEKA ne remplace pas vos équipes. Il leur donne davantage de capacité.":"LEKA does not replace your teams. It gives them more capacity.",
"Gouvernance":"Governance","Votre technologie. Vos règles.":"Your technology. Your rules.","LEKA s'adapte à votre environnement et à vos règles d'accès.":"LEKA adapts to your environment and your access rules.",
"Accès contrôlés :":"Controlled access:","chaque utilisateur dispose des capacités qui lui sont autorisées.":"each user has the capabilities they are authorized for.","Actions maîtrisées :":"Controlled actions:","vous définissez ce que LEKA peut analyser, recommander ou exécuter.":"you define what LEKA can analyze, recommend or execute.","Traçabilité :":"Traceability:","les interactions et les actions restent visibles et contrôlables.":"interactions and actions remain visible and controllable.",
"Analyser":"Analyze","Recommander":"Recommend","Exécuter":"Execute","Autorisé pour toute l'équipe":"Allowed for the whole team","Validation humaine requise":"Human approval required",
"14:32 · Nora a demandé une analyse":"14:32 · Nora requested an analysis","14:33 · LEKA · 4 sources consultées":"14:33 · LEKA · 4 sources consulted","14:41 · Nora a validé la correction":"14:41 · Nora approved the fix","activé":"enabled","désactivé":"disabled","par l'administrateur":"by the administrator",
"Un environnement qui évolue":"An evolving environment","Votre entreprise change en permanence. LEKA aussi.":"Your company is constantly changing. So is LEKA.",
"Nouveau code":"New code","Nouvelle infrastructure":"New infrastructure","Nouvelle version":"New version","Nouvelle dépendance":"New dependency","Nouvel incident":"New incident","Nouvelle décision":"New decision","Nouvelle équipe":"New team",
"LEKA actualise continuellement sa compréhension de votre environnement pour que le contexte reste pertinent.":"LEKA continuously updates its understanding of your environment so the context stays relevant.","Pas un instantané.":"Not a snapshot.","Un environnement vivant.":"A living environment.",
"Votre stack peut faire plus.":"Your stack can do more.","Donnez-lui une intelligence pour comprendre ce qui existe, découvrir ce qui est possible et agir au bon moment.":"Give it intelligence to understand what exists, discover what is possible and act at the right moment.","Comprenez. Décidez.":"Understand. Decide.","Agissez.":"Act.","Demander une démonstration →":"Request a demo →",
/* À propos */
"À propos":"About","Le système nerveux technologique de votre entreprise.":"The technological nervous system of your company.",
"LEKA aide les équipes à comprendre leur environnement technologique et à passer directement du besoin à l'action.":"LEKA helps teams understand their technology environment and go straight from need to action.",
"Pourquoi LEKA":"Why LEKA","Les entreprises ne manquent pas de technologie. Elles manquent de pouvoir l'exploiter : chaque outil, chaque service et chaque donnée vit dans son coin, et le contexte se reconstruit à la main à chaque question.":"Companies don't lack technology. They lack the ability to use it: every tool, service and dataset lives in its own corner, and the context is rebuilt by hand for every question.",
"Ce que fait LEKA":"What LEKA does","LEKA relie vos outils, en comprend les relations et répond à votre intention en mobilisant ce qui est nécessaire. Vous gardez la main : vous définissez ce que LEKA peut analyser, recommander ou exécuter.":"LEKA connects your tools, understands how they relate and answers your intent by mobilizing what is needed. You stay in control: you define what LEKA can analyze, recommend or execute.",
"Qui est derrière LEKA":"Who is behind LEKA","LEKA est édité par HEROASAP LTD, société basée à Londres. Les informations légales complètes figurent dans les mentions légales.":"LEKA is published by HEROASAP LTD, a company based in London. Full legal information is in the legal notice.","Nous contacter":"Contact us",
/* FAQ */
"Questions fréquentes":"Frequently asked questions","Les réponses aux questions que l'on nous pose le plus souvent.":"Answers to the questions we are asked most often.",
"Qu'est-ce que LEKA ?":"What is LEKA?","LEKA est une intelligence qui comprend votre environnement technologique, ses relations et ses capacités, pour répondre directement à votre besoin.":"LEKA is an intelligence that understands your technology environment, its relationships and its capabilities, to answer your need directly.",
"Quels outils LEKA peut-il connecter ?":"Which tools can LEKA connect?","Code, tickets, documentation, cloud, données, infrastructure et supervision. La liste détaillée se trouve sur la page Connecteurs.":"Code, tickets, documentation, cloud, data, infrastructure and monitoring. The detailed list is on the Connectors page.",
"LEKA peut-il agir sans mon accord ?":"Can LEKA act without my approval?","Non. Vous définissez ce que LEKA peut analyser, recommander ou exécuter, et l'exécution demande une validation humaine.":"No. You define what LEKA can analyze, recommend or execute, and execution requires human approval.",
"Qui a accès à quoi ?":"Who has access to what?","Chaque utilisateur dispose uniquement des capacités qui lui sont autorisées, et les interactions restent visibles et traçables.":"Each user only has the capabilities they are authorized for, and interactions remain visible and traceable.",
"LEKA est-il disponible ?":"Is LEKA available?","LEKA est en accès anticipé. Demandez une démonstration pour échanger avec l'équipe.":"LEKA is in early access. Request a demo to talk with the team.",
"Comment contacter l'équipe ?":"How do I contact the team?","Écrivez à support@leka-core.com ou utilisez le formulaire de contact.":"Write to support@leka-core.com or use the contact form."
  } };
  const H = { en: { h1: 'Give your stack <span class="grad">intelligence</span>.' } };
  const K = new Set(Object.values(D).flatMap(Object.keys));
  const L = () => document.documentElement.lang || 'fr';
  window.T = (s) => { const d = D[L()]; return d && d[s] !== undefined ? d[s] : s; };
  const run = () => {
    const l = L(), d = D[l] || {};
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      if (n.parentElement.closest('footer,header,script,style,[data-i18n]')) continue;
      if (n.__o === undefined) { if (!K.has(n.nodeValue.trim())) continue; n.__o = n.nodeValue; }
      const t = n.__o.trim(), r = d[t] !== undefined ? d[t] : t;
      n.nodeValue = n.__o.replace(t, () => r);
    }
    document.querySelectorAll('[data-h]').forEach((el) => {
      if (el.__o === undefined) el.__o = el.innerHTML;
      const h = H[l]; el.innerHTML = h && h[el.dataset.h] !== undefined ? h[el.dataset.h] : el.__o;
    });
    document.querySelectorAll('header .nav a, header .signin, header .btn').forEach((a) => {
      if (a.__o === undefined) a.__o = a.textContent; if (!a.hasAttribute('data-i18n')) a.textContent = d[a.__o.trim()] !== undefined ? d[a.__o.trim()] : a.__o;
    });
  };
  new MutationObserver(run).observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
  document.addEventListener('DOMContentLoaded', run); run();
})();
