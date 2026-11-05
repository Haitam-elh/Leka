---
titre: "La bonne bibliothèque"
description: "Choisir la bibliothèque d'interface adaptée à un besoin, en partant de ce qu'on repère dans le code (composant refait à la main, liste énorme, nombre animé à la main) : primitives accessibles, palette de commandes, notifications, code à usage unique, animation, nombres animés, graphiques, glisser-déposer, listes longues, état, classes et thème."
---

# La bonne bibliothèque

Beaucoup de défauts d'interface viennent d'un composant refait à la main alors
qu'une bibliothèque mûre gère déjà l'accessibilité, le focus, les cas limites
et le mouvement : un menu en `<div>` sans clavier, des notifications bricolées
dans une modale, une liste de 2 000 lignes rendue d'un coup.

## La règle de LEKA

1. **On part du besoin**, jamais d'un nom cité : « afficher un menu
   déroulant » est un besoin de primitive accessible.
2. **On regarde ce que le dépôt a déjà** (`package.json`). Une bibliothèque de
   cette page déjà présente : on s'en sert. Une concurrente présente : on le
   note, sans proposer d'en changer.
3. **On recommande une seule bibliothèque**, avec ce qu'elle remplace et
   pourquoi, en une phrase.
4. **Un besoin absent de cette page** : on le dit, et on recommande en le
   signalant clairement.

Une bibliothèque absente du dépôt est **une recommandation du livrable** : elle
n'entre jamais dans une modification proposée sans être annoncée comme une
nouvelle dépendance.

## Ce qu'on repère, ce qu'on recommande

| Ce qu'on repère dans le code | Le besoin | La bibliothèque |
| --- | --- | --- |
| un menu, un dialogue, un popover en `<div>` avec un focus géré à la main | des primitives accessibles (piège du focus, fermeture, clavier) | Base UI, ou Radix s'il est déjà là |
| une recherche de commandes faite main | une palette de commandes (⌘K) | cmdk |
| des notifications faites main, ou passées par une bibliothèque de modales | des notifications | Sonner (`notifications-sonner.md`) |
| six champs d'une lettre pour un code reçu | la saisie d'un code à usage unique | input-otp |
| des valeurs réglées par essais successifs dans le code | un panneau de réglage à l'œil | Leva |
| des ressorts, des sorties de composants, des mises en page animées écrits à la main | une animation générale | Motion |
| un nombre animé en rendant le texte à nouveau à chaque image | des nombres animés (compteurs, prix) | NumberFlow |
| du code coloré à la main ou mal | la coloration syntaxique | Shiki |
| des images de partage dessinées à la main | des images générées depuis du HTML et du CSS | Satori |
| des graphiques dessinés en SVG à la main | des graphiques, tableaux de bord | Recharts |
| un flux de données qui défile vite | un graphique temps réel | une bibliothèque de graphiques temps réel dédiée, ou Recharts si le flux est lent |
| un glisser-déposer fait main | le glisser-déposer | dnd kit |
| plus de 1 000 lignes rendues d'un coup | une liste virtualisée, avant toute astuce de pagination | Virtuoso ou TanStack Virtual |
| un état partagé passé de props en props sur plusieurs niveaux | un magasin d'état | Zustand |
| des chaînes de classes en ternaires imbriqués | des classes conditionnelles | clsx |
| un composant aux vraies variantes (taille, intention, état) écrites en conditions | des variantes typées pour Tailwind | cva |
| un flash de thème au chargement | thème clair / sombre sans flash | next-themes |

Pour un survol ou un fondu, aucune bibliothèque : une transition CSS. clsx pour
une condition ponctuelle ; cva quand un composant a de vraies variantes qui
méritent une API typée.
