---
titre: "Une application web qui se sent native sur téléphone"
description: "Les corrections de plateforme qui séparent un site affiché sur téléphone d'une application qu'on croirait installée : survol collé, flash au toucher, hauteur d'écran, zoom sur les champs et bon clavier, appui en retard, défilement qui s'échappe, encoche, sélection à l'appui long, gestes et carrousels, barre d'état ; la base à poser, ce qu'on ne livre jamais et ce qu'on rend."
---

# Une application web qui se sent native sur téléphone

La plupart des « ça rame sur mobile » ne viennent pas des animations : un délai
au toucher, un flash gris à chaque appui, un survol qui ne part plus. Ces
défauts ne se reproduisent pas dans l'émulation d'un navigateur de bureau. Le
téléphone fait foi : ce qui ne se vérifie pas dans le code se dit « à confirmer
sur un vrai téléphone ».

Ce que LEKA s'impose : chaque correction a sa raison et ne s'applique que là où
elle vaut (`user-select: none` sur un bouton, jamais sur du contenu) ; on
interroge les capacités (`hover`, `pointer`, `env()`, `dvh`), jamais le
navigateur ni la largeur d'écran pour deviner le tactile ; tactile et souris
coexistent (tablettes avec pavé, ordinateurs tactiles) ; **on n'interdit jamais
le zoom**, on corrige ce qui le déclenche.

## De symptôme à correction

| On voit | La cause | On fait |
| --- | --- | --- |
| un état de survol qui reste après l'appui | un écran tactile simule le survol au premier appui et le laisse | toute règle de survol sous `@media (hover: hover) and (pointer: fine)` (les deux conditions) ; le retour tactile passe par `:active` ; avec Tailwind v4, la variante `hover:` est déjà conditionnée |
| un flash gris ou bleu à chaque appui | le surlignage par défaut du navigateur | `html { -webkit-tap-highlight-color: transparent; }`, puis un `:active` sur tout ce qui se touche, puisqu'on a retiré le seul retour du navigateur |
| une mise en page à la mauvaise hauteur | `100vh` ignore la barre d'adresse : au chargement l'élément déborde et un bouton collé en bas passe dessous | `100dvh` qui suit la barre (coque d'application, tiroirs) ; `100svh` qui ne déborde jamais (première page, sans saut au défilement) |
| la page qui zoome sur un champ | iOS zoome sur un champ de moins de 16 px au focus et ne dézoome pas | 16 px minimum dans les champs, au besoin seulement sous `@media (pointer: coarse)` |
| le mauvais clavier | aucun indice donné au navigateur | `inputmode` numérique ou décimal, `type="email"` et `type="tel"`, `autocapitalize="none"` et `autocorrect="off"` pour un identifiant, `enterkeyhint` pour dire ce que fait la touche Entrée |
| un appui qui paraît en retard | l'attente d'un double toucher, ou un retour qui n'arrive qu'au relâchement | `touch-action: manipulation` sur boutons et liens ; un style `:active` ; `pointerdown` plutôt que `click` en JavaScript ; retour de 100 à 160 ms avec la courbe d'entrée du dépôt |
| « tirer pour rafraîchir » qui prend le défilement, la page qui bouge derrière un tiroir | le défilement qui s'échappe | `overscroll-behavior: none` sur `html, body` dans une application à défilements internes ; `overscroll-behavior: contain` sur un conteneur défilant (contenu de tiroir, fil de messages) ; jamais un `touchmove` avec `preventDefault()` |
| un contenu sous l'encoche ou sous la barre d'accueil | les marges de sécurité ignorées | la balise viewport avec `viewport-fit=cover`, puis `env(safe-area-inset-top)` et `env(safe-area-inset-bottom)` (avec une valeur de repli dans un `calc`) sur l'en-tête fixe, la barre du bas, les notifications et les tiroirs ; sans la balise, ces valeurs valent 0 |
| un appui long qui sélectionne le texte d'un bouton | la sélection par défaut | sur les commandes seulement (boutons, onglets, puces, poignées) : `user-select: none`, `-webkit-user-select: none`, `-webkit-touch-callout: none` ; jamais sur `body`, on doit pouvoir copier une adresse, une erreur, un numéro de commande |
| un carrousel qui fait défiler la page | le navigateur garde tous les gestes | `touch-action: pan-y` sur un carrousel horizontal, `none` sur une surface qui gère tout (et seulement elle), `pan-x` sur une poignée de tiroir vertical ; un carrousel natif avec `scroll-snap-type: x mandatory` et `scroll-snap-align: start` : la physique du navigateur vaut mieux qu'un ressort fait main |
| une barre d'état de la mauvaise couleur | un seul `theme-color`, ou aucun | une balise `theme-color` par thème (`media="(prefers-color-scheme: light)"` et `dark`) de la couleur du haut de page, et `color-scheme: light dark` ; avec Next.js par l'export `viewport` ; si le thème change par une classe, mettre la balise à jour |

## La base à poser

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content" />
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#ffffff" />
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0f1020" />
```

```css
html {
  -webkit-tap-highlight-color: transparent;
  -webkit-text-size-adjust: 100%;
  overscroll-behavior: none;
}
input, textarea, select { font-size: 16px; }
button, a, [role="button"] {
  touch-action: manipulation;
  user-select: none;
  -webkit-user-select: none;
}
@media (hover: hover) and (pointer: fine) {
  /* toutes les règles :hover ici */
}
```

`interactive-widget=resizes-content` fait réagir la mise en page au clavier
virtuel sur Android comme sur iOS. Sur une page documentaire où « tirer pour
rafraîchir » est bienvenu, on retire `overscroll-behavior: none`.

## Ce qu'on ne livre jamais

| Jamais | À la place |
| --- | --- |
| `user-scalable=no` ou `maximum-scale=1` | des champs à 16 px |
| un `:hover` sans condition | `@media (hover: hover) and (pointer: fine)` |
| `100vh` pour une coque d'application | `100dvh` |
| `100dvh` pour une première page | `100svh` |
| un retour seulement au `click` | `:active`, `pointerdown` |
| `touchmove` avec `preventDefault()` | `overscroll-behavior` |
| `user-select: none` sur `body` | seulement sur les commandes |
| `touch-action: none` sur ce qu'on doit pouvoir faire défiler | `pan-x` ou `pan-y` |
| `env(safe-area-inset-*)` sans `viewport-fit=cover` | la balise viewport |
| un seul `theme-color` | un par thème |
| deviner le tactile par le navigateur | les requêtes `hover` et `pointer` |

## Ce qu'on rend

Le symptôme reconnu et sa cause en une ligne ; la correction exacte (fichier,
déclaration) ; ce qui se vérifie dans le code et ce qui demande un vrai
téléphone : survol collé, flash, barre d'adresse, zoom, encoche, clavier. Pour
cela : un câble, le serveur de développement ouvert sur le réseau local,
l'inspecteur à distance du navigateur, et un téléphone de quelques années
plutôt que le dernier modèle.
