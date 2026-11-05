---
titre: "Les notifications avec Sonner"
description: "Juger, corriger et dépanner des notifications Sonner dans une application React : la mise en place (un seul Toaster, des appels côté client), l'appel qui convient à chaque besoin, mettre à jour et garder une notification, la styliser du plus léger au plus complet, les pannes fréquentes et les réglages utiles."
---

# Les notifications avec Sonner

Sonner affiche des notifications dans une application React. Ce guide sert à
relire son usage dans un dépôt et à corriger ce qui cloche. On commence par les
pannes, parce que c'est presque toujours par là qu'on arrive.

## Les pannes fréquentes

| On voit | La cause | On corrige |
| --- | --- | --- |
| rien n'apparaît | aucun Toaster monté, ou démonté (rendu conditionnel, monté par page), ou `toast()` appelé côté serveur | un seul Toaster, à la racine ; l'appel côté client |
| tout apparaît deux fois | deux Toaster (dans le layout et dans une page), ou un effet rejoué en mode strict | un seul Toaster ; appeler depuis l'événement, ou donner un `id` stable |
| les classes Tailwind n'ont aucun effet | les styles de Sonner l'emportent | `!important`, `unstyled`, ou le mode sans style |
| des notifications sans aucun style | la feuille de styles injectée s'est perdue (certains frameworks, transitions de vue) | l'importer explicitement |
| sans style dans un Shadow DOM | les styles partent dans `document.head` | les copier dans la racine fantôme |
| derrière une modale, ou coupée | un ancêtre crée un contexte d'empilement (`transform`, `filter`, `overflow`) | monter le Toaster à la racine du document |
| le mode sombre ignoré | le thème vaut `light` par défaut et ne suit pas le système | `theme="system"`, ou le thème résolu du fournisseur de thème |
| succès et erreurs en gris | c'est le réglage par défaut | `richColors` |
| une notification qui ne part jamais | `duration: Infinity`, `dismissible: false`, ou une promesse jamais réglée | le bon réglage, une promesse qui se résout ou échoue |
| `toast.promise` bloqué sur le chargement | il ne reçoit pas une promesse, ou une fonction qui en renvoie une | lui en passer une qui se règle |
| le balayage dans le mauvais sens | il découle de `position` | `swipeDirections` |
| trop près du bord sur téléphone | le décalage par défaut | `offset` sur bureau, `mobileOffset` sous 600 px |

## La mise en place

Deux pièces, pas une de plus :

1. **Un seul `<Toaster />`**, monté le plus haut possible (dans Next.js, le
   layout racine, où il fonctionne même dans un composant serveur). Jamais par
   page, jamais conditionnel : un second Toaster double chaque notification.
2. **`toast()` appelé côté client** : dans un gestionnaire d'événement, un
   effet, un rappel. C'est une simple fonction, sans hook ni fournisseur. Côté
   serveur elle ne fait rien : une action serveur renvoie son résultat, et c'est
   le client qui appelle `toast()`.

## L'appel qui convient

| Besoin | Appel |
| --- | --- |
| un message | `toast("Titre")`, avec `{ description }` pour une seconde ligne |
| succès, erreur, information, avertissement | `toast.success(…)`, `toast.error(…)`, `toast.info(…)`, `toast.warning(…)` |
| un chargement dont on gère l'état | `toast.loading(…)`, puis mise à jour par son `id` |
| chargement puis succès ou erreur d'une promesse | `toast.promise(promesse, { loading, success, error })` |
| un bouton d'action | `{ action: { label, onClick } }` (ferme la notification, sauf `event.preventDefault()`) ; `cancel` pour l'action secondaire |
| du JSX dans le cadre par défaut | `toast(<jsx />)` |
| du JSX sans aucun style | `toast.custom((t) => <jsx />)` |

Et autour :

- **mettre à jour** : rappeler `toast()` avec le même `id`, ou changer de type
  (`toast.success("Envoyé", { id })`) ;
- **garder** : `{ duration: Infinity }` ; **fermer** : `toast.dismiss(id)`, ou
  toutes sans argument ; **lister** : `useSonner()` ou `toast.getActiveToasts()` ;
- **plusieurs Toaster** : un `id` chacun et `toasterId` dans l'appel, sinon
  chaque Toaster affiche tout ;
- **à la fermeture** : `onDismiss` (bouton, balayage) et `onAutoClose`
  (minuteur) sont distincts.

## Styliser, du plus léger au plus complet

1. Les réglages par défaut, `richColors` pour des succès et erreurs colorés,
   `invert` pour inverser par rapport au thème.
2. Des retouches en ligne : `toastOptions={{ style }}` pour toutes, `style`
   pour une.
3. Des classes par partie : `toastOptions={{ classNames: { toast, title,
   description, actionButton, cancelButton, closeButton } }}`. Les styles de
   Sonner gagnent : il faut `!important` (`!text-red-900` avec Tailwind). Au-delà
   de quelques-unes, on passe à l'étape suivante.
4. **Sans style** : `toast.custom()` avec son propre JSX, en gardant le
   placement, l'empilement et le balayage. C'est la bonne fin pour une
   notification de système de design, derrière une fonction `toast()` du dépôt.

Les icônes : `icons` sur le Toaster, `icon` sur un appel, `null` pour les
retirer.

## Les réglages utiles

Sur le Toaster : `theme`, `richColors`, `expand`, `visibleToasts` (3 par
défaut), `id`, `position` (`bottom-right` par défaut), `closeButton`, `offset`,
`mobileOffset`, `swipeDirections`, `dir`, `hotkey`, `invert`, `toastOptions`,
`gap`, `icons`.

Sur un appel : `description`, `duration` (4 000 ms par défaut), `dismissible`,
`icon`, `action`, `cancel`, `id`, `toasterId`, `unstyled`, `classNames`,
`onDismiss`, `onAutoClose`.
