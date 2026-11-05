---
titre: "Écrire du Swift moderne"
description: "Relire ou proposer du Swift et du SwiftUI au niveau actuel, avec une règle : le plus simple d'abord, la dynamique seulement quand on peut nommer sa raison. Types valeurs, erreurs et optionnels, concurrence par paliers, Sendable, tâches structurées, SwiftUI, protocoles et génériques, conception d'API, performance et mémoire, tests, journalisation et syntaxe moderne."
---

# Écrire du Swift moderne

Une règle tient tout le guide : **le plus simple, le plus statique, sur un seul
fil d'abord ; la dynamique (concurrence, références, existentiels, pointeurs)
seulement là où l'on peut nommer la raison.** Une revue de LEKA demande, à
chaque choix plus complexe que nécessaire : quelle est la raison ?

| Besoin | D'abord | Plus loin seulement si |
| --- | --- | --- |
| des données | `struct`, `enum` | il faut une identité, un partage, un héritage |
| une abstraction | un type concret | du code se répète entre types |
| du polymorphisme | `some P` | il faut stocker des types différents : `any P` |
| l'exécution | l'acteur principal, en synchrone | le profilage montre un blocage : `async`, puis `@concurrent`, puis `actor` |
| la mémoire | `Array`, `String` | le profilage montre le coût : `InlineArray`, `Span` |
| la sûreté | une API sûre | interopérabilité C ou chemin critique mesuré : `Unsafe*` |

## Ce qu'on vérifie, sujet par sujet

### Les données

- `struct` et `enum` par défaut ; `class` pour une identité, un état partagé
  modifiable, un héritage ou la durée de vie d'une ressource.
- `let` par défaut, `var` seulement quand on modifie.
- Une structure qui contient une classe modifiable n'est ni une valeur ni une
  référence : ses copies partagent l'objet. Soit la classe est immuable, soit
  on l'enveloppe en copie à l'écriture (`isKnownUniquelyReferenced`).
- Des états exclusifs s'écrivent en un seul `enum State`, pas en une pile
  d'optionnels qui autorise des combinaisons impossibles.
- Une possession unique s'exprime par un type non copiable (`~Copyable`), et la
  méthode qui le termine est `consuming`.

### Les erreurs et les optionnels

- Ce qui se récupère : `throw`. Une erreur de programmation : `precondition` ou
  `fatalError`.
- Les types d'erreur sont des `enum` avec valeurs associées : c'est le contexte
  qui aide à corriger.
- `guard` pour sortir sur une erreur, `if let` pour le reste.
- `throws(UneErreur)` en interne et dans le générique ; `throws` simple pour une
  API publique.
- On ne force un optionnel que si l'on sait énoncer l'invariant, de préférence
  dans un message.

### La concurrence, par paliers

On monte d'un palier seulement quand le précédent ne suffit plus :

1. **tout sur l'acteur principal, sans concurrence** : la plupart des
   applications s'arrêtent là ;
2. **`async` et `await`** pour cacher une latence (réseau, disque), sans
   concurrence à soi ;
3. **`@concurrent`** pour sortir *son propre* travail coûteux du fil principal,
   seulement après qu'Instruments a montré un blocage ;
4. **`actor`** pour sortir *un état* de l'acteur principal, quand trop
   d'allers-retours le justifient.

Réglages du projet : la concurrence « accessible » activée partout ;
l'isolation par défaut sur l'acteur principal pour les modules d'application et
d'interface, pas pour une bibliothèque, qui expose des API `nonisolated`.

Depuis Swift 6.2, **une fonction `async` reste sur l'acteur qui l'appelle** :
`@concurrent` part toujours sur le pool parallèle, `nonisolated` s'exécute là où
on l'appelle (le bon défaut pour une bibliothèque).

```swift
nonisolated struct AnalyseDocument {
  @concurrent
  func analyser(_ contenu: Data) async -> Resume {
    async let mots = compterMots(contenu)
    async let langue = detecterLangue(contenu)
    return await Resume(mots: mots, langue: langue)
  }
}
```

- Profiler avant de déporter ; pas de tâche pour un travail trivial ; une tâche
  par opération de bout en bout.
- **`await` casse l'atomicité** : l'état peut changer pendant la suspension. On
  revérifie après, et l'on ne garde jamais un verrou au travers.
- Un acteur garantit l'exclusion, pas une transaction : son état se modifie dans
  des méthodes synchrones. Le piège classique (un cache vide, deux
  téléchargements, le second écrase le premier) se règle en revérifiant après
  `await` ou en dédoublonnant le travail en cours. Un acteur n'est pas une file
  dans l'ordre d'arrivée.

### Sendable

- Une valeur est `Sendable` si son stockage l'est (déduit en interne, déclaré en
  public). Les acteurs et les classes `@MainActor` le sont.
- La plupart des classes de modèle ne sont ni `@MainActor` ni `Sendable` ; on
  peut *transmettre* un objet non `Sendable` si l'émetteur cesse de s'en servir.
- `@unchecked Sendable` seulement avec une vraie synchronisation (`Mutex`).
- Face à une erreur de course, dans l'ordre : ne pas partager ; en faire une
  valeur `Sendable` ; l'isoler dans un acteur ; puis seulement `Mutex` ou
  `Atomic`.
- Les variables globales en sont la première source : `let`, puis `@MainActor`,
  puis `Mutex`, et en dernier `nonisolated(unsafe)`.

### Les tâches structurées

- `async let` pour un nombre fixe d'enfants ; `withTaskGroup` pour un nombre
  variable, en lisant les résultats au fil de l'eau ; `withDiscardingTaskGroup`
  quand les enfants ne renvoient rien.
- `Task { }` seulement quand la durée de vie ne tient pas dans un bloc ;
  `Task.detached` presque jamais.
- L'annulation est coopérative : `Task.isCancelled` ou
  `Task.checkCancellation()` avant un travail coûteux.
- On borne la concurrence au lieu de lancer un enfant par élément d'une liste
  sans fin.
- Une continuation se reprend **exactement une fois**, sur chaque chemin.
- `AsyncStream` pour adapter une API à rappels.

### SwiftUI

- `View` est isolée sur l'acteur principal, son `@State` aussi.
- Certaines fermetures tournent hors du fil principal (`visualEffect`,
  `Shape.path(in:)`, `Layout`, `onGeometryChange`) : on y capture la valeur utile
  au lieu d'envoyer `self`.
- Les rappels d'action sont synchrones exprès : le changement d'état animé
  (`withAnimation`) a lieu dans la même image que l'événement ; une `Task`
  seulement pour le travail long qui suit.

### Protocoles et génériques

- Ni classe ni protocole au départ : des types concrets, puis un protocole quand
  du code se répète, puis du générique.
- Une exigence de protocole est un point de personnalisation (répartition
  dynamique) ; une méthode seulement dans une extension est statique et peut
  être masquée.
- La composition plutôt que l'héritage ; un transtypage forcé est un signal.
- `some P` par défaut ; `any P` pour stocker des types différents, avec son coût
  (types associés effacés, appels opaques pour l'optimiseur).

### La conception d'API

- La clarté au point d'usage d'abord ; pas de préfixes ; pas de `get` en tête.
- Le contrôle d'accès documente ; on rend les états impossibles impossibles à
  écrire (setters privés, `enum`, identifiants typés).
- Les property wrappers pour une politique d'accès, les result builders pour un
  langage dédié, les macros pour le code que le compilateur pourrait écrire.

### La performance et la mémoire

- L'algorithme d'abord (`removeAll(where:)` plutôt que `remove(at:)` en
  boucle), puis Instruments.
- `final` sur les classes qu'on ne dérive pas ; l'optimisation du module entier.
- Copie à l'écriture pour les grandes structures copiées souvent.
- `[UnModele]` plutôt que `[any Modele]` quand c'est possible.
- `InlineArray` et `Span` pour un stockage contigu sans risque.
- La durée de vie garantie d'un objet s'arrête à son dernier usage : `weak` ou
  `unowned` seulement pour casser un cycle, et mieux encore, ne pas le créer.

### Les tests

Swift Testing pour tout nouveau test : `@Test`, `#expect(expression)`,
`try #require(...)` pour s'arrêter et déballer ; des suites en `struct` ;
`@Test(arguments:)` plutôt qu'une boucle ; des traits (`.disabled("raison")`,
`.bug`, `.tags`, `.timeLimit`) ; `withKnownIssue` pour un échec qui ne dépend pas
de nous. Les tests tournent en parallèle et dans un ordre aléatoire. XCTest reste
pour l'automatisation d'interface et les mesures de performance.

### La journalisation

`Logger` (de `os`) plutôt que `print` ; les valeurs non numériques sont masquées
par défaut, `privacy: .public` seulement pour ce qui n'est pas personnel ; un
identifiant de corrélation pour suivre toute l'histoire d'un échec.

## La syntaxe d'aujourd'hui

| Au lieu de | Écrire |
| --- | --- |
| des ternaires imbriqués, une fermeture appelée pour initialiser | des expressions `if` et `switch` |
| `ObservableObject` et `@Published` partout | `@Observable` |
| scruter un objet pour ses changements | `Observations { … }` |
| des calculs d'index dans une chaîne | les expressions régulières de Swift |
| `withUnsafeBufferPointer` | `.span` |
| des noms de tests contorsionnés | des identifiants bruts dans `@Test` |

On vérifie la version de la chaîne d'outils du projet avant d'employer une
nouveauté.
