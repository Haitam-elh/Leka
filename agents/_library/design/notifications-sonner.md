---
titre: Les notifications avec Sonner
description: Mettre en place, appeler, styliser et dépanner des notifications Sonner dans une application React — un seul Toaster, le bon appel selon le besoin, mise à jour et persistance, l'échelle de personnalisation jusqu'au mode sans style, le thème, et un tableau des pannes fréquentes avec leur cause.
---

# Les notifications avec Sonner

Sonner est une bibliothèque de notifications pour React. Ce guide sert à
juger ou corriger son usage dans un dépôt.

## La mise en place

Deux pièces, pas une de plus :

1. **Un seul `<Toaster />`**, monté le plus haut possible (dans Next.js, le
   `layout` racine — il fonctionne dans un composant serveur). Jamais par
   page ni conditionnel : un second Toaster double chaque notification.
2. **`toast()` appelé côté client** — dans un gestionnaire d'événement, un
   effet, un rappel. C'est une simple fonction, sans hook ni fournisseur ;
   côté serveur elle ne fait rien : une action serveur renvoie son résultat,
   et le client appelle `toast()`.

## Le bon appel

| Besoin | Appel |
| --- | --- |
| un message | `toast("Titre")`, avec `{ description }` pour une seconde ligne |
| un succès, une erreur, une info, un avertissement | `toast.success(…)`, `toast.error(…)`… |
| un chargement dont on gère soi-même l'état | `toast.loading(…)`, puis mise à jour par son id |
| chargement puis succès ou erreur d'une promesse | `toast.promise(promesse, { loading, success, error })` |
| un bouton d'action | `{ action: { label, onClick } }` (ferme la notification, sauf `event.preventDefault()`) ; `cancel` pour l'action secondaire |
| un contenu JSX dans le cadre par défaut | `toast(<jsx />)` |
| un contenu JSX sans aucun style | `toast.custom((t) => <jsx />)` |

- **Mettre à jour** : rappeler `toast()` avec le même `id`, ou changer de type
  (`toast.success("Envoyé", { id })`).
- **Garder** : `{ duration: Infinity }`. **Fermer** : `toast.dismiss(id)`, ou
  tout. **Lister** : `useSonner()`, ou `toast.getActiveToasts()`.
- **Plusieurs Toaster** : un `id` chacun, et `toasterId` dans l'appel ; sans
  cela, chaque Toaster affiche tout.
- **À la fermeture** : `onDismiss` (bouton, balayage) et `onAutoClose`
  (minuteur) sont distincts.

## Styliser, du plus léger au plus complet

1. Les réglages par défaut, `richColors` pour des succès et erreurs colorés,
   `invert` pour inverser par rapport au thème.
2. Des retouches en ligne : `toastOptions={{ style }}` pour toutes, `style`
   pour une.
3. Des classes par partie : `toastOptions={{ classNames: { toast, title,
   description, actionButton, cancelButton, closeButton } }}` — les styles de
   Sonner l'emportent : il faut `!important` (`!text-red-900` en Tailwind).
   Si l'on en marque beaucoup, on passe à l'étape suivante.
4. **Sans style** : `toast.custom()` avec son propre JSX, en gardant le
   placement, l'empilement et le balayage. C'est la bonne fin pour une
   notification de système de design, derrière sa propre fonction `toast()`.

Les icônes : `icons` sur le Toaster, `icon` sur un appel, `null` pour retirer.
Le **thème** vaut `light` par défaut et ne suit pas le système : `theme="system"`,
ou le thème résolu du fournisseur de thème.

## Les pannes fréquentes

| Symptôme | Cause et correction |
| --- | --- |
| rien n'apparaît | aucun Toaster monté, ou démonté (rendu conditionnel, par page) — un seul, à la racine ; ou `toast()` appelé côté serveur |
| tout apparaît deux fois | deux Toaster (layout et page) ; ou un effet rejoué en mode strict — appeler depuis l'événement, ou donner un `id` stable |
| les classes Tailwind n'ont aucun effet | les styles par défaut gagnent — `!important`, `unstyled`, ou le mode sans style |
| des notifications sans aucun style | la feuille de styles injectée a été perdue (certains frameworks, transitions de vue) — l'importer explicitement |
| sans style dans un Shadow DOM | les styles vont dans `document.head` — les copier dans la racine fantôme |
| derrière une modale, ou coupée | un ancêtre crée un contexte d'empilement (`transform`, `filter`, `overflow`) — monter le Toaster à la racine du document |
| le mode sombre ignoré | `theme` vaut `light` — `theme="system"` ou le thème résolu |
| succès et erreurs en gris | c'est le défaut — `richColors` |
| une notification qui ne part jamais | `duration: Infinity`, `dismissible: false`, ou une promesse qui ne se règle jamais |
| `toast.promise` bloqué sur le chargement | il lui faut une promesse (ou une fonction qui en renvoie une) qui se résout ou échoue |
| le balayage dans le mauvais sens | il découle de `position` — `swipeDirections` |
| trop près du bord sur téléphone | `offset` (bureau) et `mobileOffset` (moins de 600 px) |

## Les réglages utiles du Toaster

`theme`, `richColors`, `expand`, `visibleToasts` (3 par défaut), `id`,
`position` (`bottom-right` par défaut), `closeButton`, `offset`,
`mobileOffset`, `swipeDirections`, `dir`, `hotkey`, `invert`, `toastOptions`,
`gap`, `icons`. Et pour un appel : `description`, `duration` (4 000 ms par
défaut), `dismissible`, `icon`, `action`, `cancel`, `id`, `toasterId`,
`unstyled`, `classNames`, `onDismiss`, `onAutoClose`.
