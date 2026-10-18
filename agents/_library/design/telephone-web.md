---
titre: Une application web qui se sent native sur téléphone
description: Les corrections de plateforme qui séparent un site affiché sur téléphone d'une application qu'on croirait installée — survol collé, flash au toucher, hauteur 100vh, zoom des champs, appui qui traîne, défilement qui s'échappe, encoche, texte sélectionné à l'appui long, carrousel, barre d'état — avec la base à poser et ce qui demande un vrai téléphone.
---

# Une application web qui se sent native sur téléphone

La plupart des « ça rame sur mobile » ne sont pas des problèmes d'animation :
c'est un délai au toucher, un flash gris à chaque appui, un survol qui ne
part plus. Ces défauts ne se reproduisent pas dans l'émulation d'un
navigateur de bureau. Le téléphone fait foi : ce qui ne se vérifie pas dans
le code se dit « à confirmer sur un vrai téléphone ».

Règles : chaque correction a sa raison et s'applique là où la raison
s'applique (`user-select: none` sur un bouton, jamais sur du contenu) ; on
interroge les capacités (`hover`, `pointer`, `env()`, `dvh`), jamais le
navigateur ou la largeur d'écran pour deviner le tactile ; le tactile et la
souris coexistent (tablettes avec pavé, ordinateurs tactiles) ; **on
n'interdit jamais le zoom** — on corrige ce qui le provoque.

## Les symptômes

| Ce qu'on voit | Ce qu'on fait |
| --- | --- |
| un état de survol qui reste après l'appui | le réserver à `@media (hover: hover) and (pointer: fine)` |
| un flash gris ou bleu à chaque appui | `-webkit-tap-highlight-color: transparent` |
| une mise en page à la mauvaise hauteur | `100dvh` (application) ou `100svh` (première page) |
| la page qui zoome sur un champ | une police d'au moins 16 px dans les champs |
| un appui qui paraît en retard | un retour à l'appui et `touch-action: manipulation` |
| le geste « tirer pour rafraîchir » qui prend le défilement | `overscroll-behavior` |
| un contenu qui s'arrête sous l'encoche | `viewport-fit=cover` et `env(safe-area-inset-*)` |
| un appui long qui sélectionne le texte d'un bouton | `user-select: none` sur les commandes |
| un carrousel qui fait défiler la page | `touch-action: pan-y` sur la surface de geste |
| une barre d'état de la mauvaise couleur | `theme-color` par thème |

## Les corrections

**Survol collé.** Un écran tactile simule le survol au premier appui et le
laisse en place. Toute règle de survol se range sous
`@media (hover: hover) and (pointer: fine)` — les deux conditions : un
pointeur qui survole, et précis. Le retour tactile passe par `:active`. (Avec
Tailwind v4, la variante `hover:` est déjà conditionnée.)

**Flash au toucher.** `html { -webkit-tap-highlight-color: transparent; }`,
une fois, puis un état `:active` sur tout ce qui se touche, puisqu'on vient
de retirer le seul retour du navigateur.

**Hauteur.** `100vh` vaut la hauteur sans la barre d'adresse : au chargement,
un élément à `100vh` déborde et un bouton collé en bas passe dessous.
`100dvh` suit la barre (coque d'application, tiroirs), `100svh` ne déborde
jamais (première page, pour éviter les sauts pendant le défilement).

**Zoom sur un champ.** iOS zoome dès qu'un champ de moins de 16 px reçoit le
focus et ne dézoome pas. On met 16 px minimum, au besoin seulement pour
`@media (pointer: coarse)`. Et on choisit le bon clavier : `inputmode`
numérique ou décimal, `type="email"` et `type="tel"`,
`autocapitalize="none"` et `autocorrect="off"` pour un identifiant,
`enterkeyhint` pour que la touche Entrée dise ce qu'elle fait.

**Appui en retard.** Deux causes : l'attente d'un double toucher
(`touch-action: manipulation` sur les boutons et liens), et un retour qui
n'arrive qu'au relâchement — on stylise `:active` et, en JavaScript, on
écoute `pointerdown` plutôt que `click`. Retour d'appui entre 100 et 160 ms,
`ease-out`, avec les jetons de courbe du dépôt.

**Défilement qui s'échappe.** `overscroll-behavior: none` sur `html, body`
dans une application à défilements internes ; `overscroll-behavior: contain`
sur un conteneur défilant (contenu d'un tiroir, fil de discussion) pour que
la page derrière ne bouge pas. Jamais un `touchmove` avec `preventDefault()`.

**Encoche et barre d'accueil.** La balise viewport avec `viewport-fit=cover`,
puis des marges `env(safe-area-inset-top)` et `env(safe-area-inset-bottom)`
(avec une valeur de repli dans un `calc`) sur l'en-tête fixe, la barre du
bas, les notifications et les tiroirs. Sans la balise, ces valeurs valent 0.

**Texte sélectionné à l'appui long.** Sur les commandes seulement (boutons,
onglets, puces, poignées) : `user-select: none`, `-webkit-user-select: none`,
`-webkit-touch-callout: none`. Jamais sur `body` : on copie une adresse, un
message d'erreur, un numéro de commande.

**Carrousel et gestes.** `touch-action` dit ce que le navigateur garde :
`pan-y` sur un carrousel horizontal, `none` sur une surface qui gère tout
(et seulement elle), `pan-x` sur une poignée de tiroir vertical. Un carrousel
en défilement natif prend `scroll-snap-type: x mandatory` et
`scroll-snap-align: start` : la physique du navigateur vaut mieux qu'un
ressort fait main.

**Barre d'état.** Une balise `theme-color` par thème
(`media="(prefers-color-scheme: light)"` et `dark`), de la couleur du haut de
la page, et `color-scheme: light dark`. Avec Next.js, par l'export
`viewport`. Si le thème change par une classe, on met la balise à jour.

## La base à poser

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content" />
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#ffffff" />
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0b0b12" />
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
sur Android comme sur iOS. On retire `overscroll-behavior: none` d'une page
documentaire où « tirer pour rafraîchir » est bienvenu.

## À ne jamais livrer

| Jamais | À la place |
| --- | --- |
| `user-scalable=no` ou `maximum-scale=1` | des champs à 16 px |
| un `:hover` sans condition | `@media (hover: hover) and (pointer: fine)` |
| `100vh` pour une coque d'application | `100dvh` |
| `100dvh` pour une première page | `100svh` |
| un retour seulement au `click` | `:active`, `pointerdown` |
| `touchmove` + `preventDefault()` | `overscroll-behavior` |
| `user-select: none` sur `body` | seulement sur les commandes |
| `touch-action: none` sur ce qu'il faut pouvoir dépasser en défilant | `pan-x` / `pan-y` |
| `env(safe-area-inset-*)` sans `viewport-fit=cover` | la balise viewport |
| un seul `theme-color` | un par thème |
| deviner le tactile par le navigateur | les requêtes `hover` et `pointer` |

## Ce qu'on rend

Le symptôme reconnu et sa raison en une ligne ; la correction exacte
(fichier, déclaration) ; ce qui se vérifie dans le code et ce qui demande un
vrai téléphone (survol collé, flash, barre d'adresse, zoom, encoche, clavier
— câble, serveur de développement ouvert sur le réseau, inspecteur à
distance, un téléphone de quelques années).
