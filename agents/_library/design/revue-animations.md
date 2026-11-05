---
titre: "Revoir des animations"
description: "Juger le mouvement d'un écran ou d'une pull request avec une barre haute : ce qui se signale sans débat, les dix exigences qu'on vérifie sur chaque animation, l'ordre des corrections, le tableau des constats, le verdict par niveau d'effet et la décision (bloquer ou approuver)."
---

# Revoir des animations

La question d'une revue du mouvement n'est pas « est-ce que ça bouge ? » mais
« est-ce que ça se ressent juste ? ». Une transition qui marche mais paraît
molle, part du mauvais endroit, revient trop souvent ou saccade est une
régression. Chez LEKA, **on signale par défaut ; l'approbation se mérite.**
Les valeurs à citer sont celles de `principes.md`, recopiées sans les arrondir.

## Ce qui se signale sans débat

- `transition: all`.
- Une entrée depuis `scale(0)`, ou un simple fondu sans transformation de
  départ.
- `ease-in` sur une interaction ; la règle de LEKA est **jamais `ease-in`**
  sur un élément d'interface. Une courbe par défaut du CSS sur un mouvement
  voulu.
- Une animation sur un raccourci clavier ou une palette de commandes.
- Plus de 300 ms sur un élément d'interface, sans raison donnée.
- `transform-origin: center` sur un menu ou une info-bulle rattachés à un
  bouton.
- Des images clés sur des notifications, des interrupteurs, tout ce qui se
  déclenche en rafale.
- L'animation de `width`, `height`, `margin`, `padding`, `top`, `left`.
- Les raccourcis `x`, `y`, `scale` de Motion sur une page qui charge.
- Une variable CSS posée sur un parent pour déplacer un enfant.
- Aucun traitement de `prefers-reduced-motion`.
- Un `:hover` animé sans condition de pointeur.
- La même durée à l'appui et au relâchement d'un geste qui demande une
  décision.
- Un groupe qui apparaît d'un bloc là où une cascade de 30 à 80 ms
  conviendrait.

## Les dix exigences

Chaque animation du périmètre passe ces dix points ; un manquement est un
constat.

| # | Exigence | Ce qu'on vérifie |
| --- | --- | --- |
| 1 | une raison | orienter, dire un état, confirmer, expliquer, éviter une rupture ; « c'est joli » sur un élément vu souvent : on bloque |
| 2 | la fréquence | rien sur une action au clavier ou vue des centaines de fois par jour ; presque rien sur ce qui revient des dizaines de fois |
| 3 | une courbe vive | la courbe d'entrée pour entrer et sortir, jamais `ease-in`, pas de courbe par défaut molle |
| 4 | la durée | sous 300 ms pour un élément d'interface, sauf raison dite |
| 5 | l'origine et la physique | un menu sort de son bouton, rien ne part de `scale(0)`, une modale reste centrée |
| 6 | l'interruption | ce qui se déclenche en rafale ou suit un geste se réoriente (transition, ressort) au lieu de repartir de zéro |
| 7 | le coût | `transform` et `opacity` ; la mise en page animée ou les raccourcis de Motion sur une page occupée sont des constats de performance |
| 8 | l'accessibilité | mouvement réduit respecté (plus doux, jamais rien) ; survol animé réservé aux pointeurs précis |
| 9 | l'asymétrie | lent quand la personne décide (appui long, confirmation destructive), rapide quand le système répond |
| 10 | la cohérence | le mouvement a le caractère du produit ; un fondu qui superpose deux états se masque d'un léger flou ; dans le doute, retirer l'animation est souvent le meilleur choix |

## L'ordre des corrections

On propose d'abord ce qui est en haut :

1. **retirer** l'animation (fréquente, sans but, lancée au clavier) ;
2. **la réduire** : plus courte, une transformation plus petite, moins de
   propriétés ;
3. **corriger la courbe** : `ease-in` vers la courbe d'entrée ;
4. **corriger l'origine et le départ** : origine sur le déclencheur,
   `scale(0.95)` avec l'opacité au lieu de `scale(0)` ;
5. **la rendre interruptible** : images clés vers transition, ressort pour un
   geste ;
6. **la rendre légère** : mise en page vers `transform` et `opacity`,
   raccourcis de Motion vers une valeur `transform` complète, Web Animations
   API pour programmer sans bibliothèque ;
7. **rendre le temps asymétrique** ;
8. **finir** : flou sur un fondu, cascade, `@starting-style`, ressort pour un
   élément vivant ;
9. **accessibilité et cohérence** : mouvement réduit, survol conditionnel,
   accord avec le caractère du composant.

## Ce que la revue rend

**Le tableau des constats**, un seul, une ligne par problème, `fichier:ligne`
cité :

| Où | Avant | Après | Pourquoi |
| --- | --- | --- | --- |
| `Dropdown.tsx:27` | `transition: all 320ms ease-in` | `transition: transform 180ms var(--ease-enter), opacity 180ms var(--ease-enter)` | il démarre lentement et anime des propriétés coûteuses que personne n'a choisies |

**Le verdict**, les remarques restantes de l'effet le plus fort au plus
faible, sans les niveaux vides :

1. ce qui sonne faux (courbe molle, apparition de nulle part, animation sur
   une action fréquente) ;
2. ce qu'il fallait simplement retirer ou réduire ;
3. la performance (propriétés coûteuses, risque de saccade) ;
4. l'interruption et le rythme ;
5. l'origine, la physique, la cohérence ;
6. l'accessibilité.

**La décision**, explicite :

- **Bloquer** : un mouvement qui sonne faux, une animation sur une action au
  clavier ou très fréquente, `scale(0)` ou `ease-in` sur l'interface, ou une
  animation coûteuse facile à corriger.
- **Approuver** : rien de tout cela, des durées et des courbes dans les bornes,
  l'interruption traitée là où il faut, le mouvement réduit respecté.

Ce qui ne se juge pas dans le code (un fondu, le rebond d'un ressort) se dit,
avec la vérification : au ralenti, image par image, et sur un vrai appareil
pour un geste.
