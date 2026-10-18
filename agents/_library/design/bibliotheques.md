---
titre: La bonne bibliothèque
description: Choisir la bibliothèque d'interface adaptée à un besoin (primitives accessibles, palette de commandes, notifications, code à usage unique, animation, nombres animés, graphiques, glisser-déposer, listes longues, état, classes, thèmes) plutôt que de la refaire à la main — et ne jamais changer de dépendance sans le dire.
---

# La bonne bibliothèque

Beaucoup de défauts d'interface viennent d'un composant refait à la main
alors qu'une bibliothèque mûre gère déjà l'accessibilité, le focus, les cas
limites et le mouvement : un menu en `<div>` sans gestion du clavier, des
notifications bricolées dans une modale, une liste de 2 000 lignes rendue
d'un coup.

Comment s'en servir :

1. **Partir du besoin**, pas du nom de bibliothèque cité : « afficher un menu
   déroulant », c'est un besoin de primitive accessible.
2. **Regarder ce que le dépôt a déjà** (`package.json`). S'il utilise déjà une
   bibliothèque de la liste, on s'en sert. S'il en utilise une concurrente, on
   le signale sans proposer d'en changer.
3. **Recommander une seule bibliothèque**, avec ce qu'elle remplace et
   pourquoi, en une phrase.
4. Si le besoin n'est pas dans la liste, on le dit, et on recommande en
   l'indiquant clairement.

Dans LEKA, une bibliothèque absente du dépôt est **une recommandation du
livrable** : elle n'entre jamais dans une modification proposée sans être
dite comme une nouvelle dépendance.

## La liste

**Composants et primitives**

| Besoin | Bibliothèque |
| --- | --- |
| composants accessibles sans style (dialogues, popovers, menus, listes de choix) | Base UI (ou Radix, s'il est déjà là) |
| palette de commandes (⌘K) | cmdk |
| notifications (toasts) | Sonner |
| saisie d'un code à usage unique | input-otp |
| panneau de réglages pour régler des valeurs à l'œil | Leva |

**Mouvement et visuels**

| Besoin | Bibliothèque |
| --- | --- |
| animation générale (ressorts, mise en page, sorties) | Motion |
| nombres animés (compteurs, prix) | NumberFlow |
| coloration syntaxique | Shiki |
| images de partage générées (HTML/CSS vers image) | Satori |

Pour un simple survol ou un fondu, pas de bibliothèque : une transition CSS.

**Graphiques**

| Besoin | Bibliothèque |
| --- | --- |
| graphiques statiques ou tableaux de bord | Recharts |
| données en temps réel qui défilent | une bibliothèque de graphiques temps réel dédiée, ou Recharts si le flux est lent |

**Interaction et performance**

| Besoin | Bibliothèque |
| --- | --- |
| glisser-déposer | dnd kit |
| listes et tableaux longs | une liste virtualisée (Virtuoso, TanStack Virtual) |

**État et style**

| Besoin | Bibliothèque |
| --- | --- |
| état partagé | Zustand |
| classes conditionnelles | clsx |
| variantes typées pour Tailwind | cva |
| thème clair / sombre sans flash au chargement | next-themes |

clsx pour des conditions ponctuelles ; cva quand un composant a de vraies
variantes (taille, intention, état) qui méritent une API typée.

## Les erreurs à repérer

- **Des notifications faites main**, ou avec une bibliothèque de modales →
  une bibliothèque de notifications.
- **Un menu ou un dialogue en `<div>`** avec un focus géré à la main → des
  primitives accessibles (piège du focus, fermeture, clavier).
- **Un nombre animé en rerendant le texte** → une bibliothèque de nombres
  animés.
- **Plus de 1 000 lignes rendues d'un coup** → une liste virtualisée avant
  toute astuce de pagination.
- **Un état partagé passé de props en props** sur plusieurs niveaux → un
  magasin d'état.
- **Des chaînes de classes imbriquées en ternaires** → clsx, ou cva si c'est
  une variante.
