---
titre: Écrire du Swift moderne
description: Relire ou proposer du Swift et du SwiftUI au niveau actuel — types valeurs, erreurs et optionnels, concurrence (rester sur l'acteur principal jusqu'à preuve du contraire, async, @concurrent, acteurs), Sendable, tâches structurées, SwiftUI, protocoles et génériques (some et any), conception d'API, performance et ARC, tests avec Swift Testing, macros, journalisation et syntaxe moderne.
---

# Écrire du Swift moderne

Le fil conducteur : **commencer par ce qui est le plus simple, le plus
statique, sur un seul fil, et ne payer la dynamique — concurrence, références,
existentiels, pointeurs — que là où l'on peut nommer la raison.**

| Besoin | D'abord | Plus loin seulement si |
| --- | --- | --- |
| des données | `struct` / `enum` | il faut une identité, un partage, un héritage |
| une abstraction | un type concret | du code se répète entre types |
| un polymorphisme | `some P` | il faut stocker des types différents → `any P` |
| l'exécution | l'acteur principal, synchrone | le profilage montre un blocage → `async` → `@concurrent` → `actor` |
| la mémoire | `Array`, `String` | le profilage montre le coût → `InlineArray`, `Span` |
| la sûreté | une API sûre | interopérabilité C ou chemin critique mesuré → `Unsafe*` |

## Les types valeurs

- `struct` et `enum` par défaut ; `class` pour une identité, un état partagé
  modifiable, un héritage ou la durée de vie d'une ressource.
- `let` par défaut, `var` seulement quand on modifie.
- Une structure qui contient une classe modifiable n'est ni une valeur ni une
  référence : les copies partagent l'objet. On garde la classe immuable, ou on
  l'encapsule en copie à l'écriture (`isKnownUniquelyReferenced`).
- Un `enum` exprime un ensemble fermé ou des états exclusifs : un seul `State`
  plutôt qu'une pile d'optionnels qui permet des combinaisons impossibles.
- Les types non copiables (`~Copyable`) expriment une possession unique ; la
  méthode qui termine est `consuming`.

## Erreurs et optionnels

- Récupérable : `throw`. Erreur de programmation : `precondition` /
  `fatalError`.
- Des `enum` avec valeurs associées comme types d'erreur : le contexte est ce
  qui compte.
- `guard` pour les conditions d'erreur, `if let` pour le reste.
- `throws(MonErreur)` pour l'interne et le générique ; `throws` simple pour
  une API publique.
- Forcer un optionnel seulement quand on peut énoncer l'invariant, de
  préférence avec un message.

## La concurrence : un seul fil jusqu'à preuve du contraire

La progression, sans sauter d'étape :

1. **Tout sur l'acteur principal, sans concurrence** — cela suffit à la
   plupart des applications.
2. **`async` / `await`** pour masquer la latence (réseau, disque) — sans
   concurrence à soi.
3. **`@concurrent`** pour sortir *son* travail coûteux du fil principal —
   seulement après qu'Instruments a montré un blocage.
4. **`actor`** pour sortir *de l'état* de l'acteur principal — quand trop
   d'aller-retours le justifient.

Réglages : la concurrence « accessible » activée partout ; l'isolation par
défaut sur l'acteur principal pour les modules d'application et d'interface ;
pas pour une bibliothèque, qui expose des API `nonisolated`.

Depuis Swift 6.2, **une fonction `async` ne quitte pas l'acteur qui l'appelle**
: `@concurrent` passe toujours au pool parallèle ; `nonisolated` s'exécute là
où on l'appelle (le bon défaut pour une bibliothèque).

```swift
nonisolated struct TraitementPhoto {
  @concurrent
  func traiter(_ donnees: Data) async -> PhotoTraitee {
    async let autocollant = extraireAutocollant(donnees)
    async let couleurs = extraireCouleurs(donnees)
    return await PhotoTraitee(autocollant: autocollant, couleurs: couleurs)
  }
}
```

- Profiler avant de déporter ; ne pas créer une tâche pour un travail
  trivial ; une tâche par opération de bout en bout.
- **`await` casse l'atomicité** : l'état peut changer pendant la suspension ;
  on revérifie après, on ne garde jamais un verrou au travers.
- Un acteur garantit l'exclusion, pas une transaction : on modifie son état
  dans des méthodes synchrones ; le piège classique (cache manquant, deux
  téléchargements, le second écrase le premier) se règle en revérifiant après
  `await` ou en dédoublonnant le travail en cours. Un acteur n'est pas FIFO.

## Sendable

- Une valeur est `Sendable` si son stockage l'est (déduit pour l'interne,
  déclaré pour le public). Acteurs et classes `@MainActor` le sont.
- La plupart des classes de modèle ne sont ni `@MainActor` ni `Sendable` ; on
  peut *transmettre* un objet non `Sendable` si l'émetteur cesse de s'en
  servir.
- `@unchecked Sendable` seulement avec une vraie synchronisation (`Mutex`).
- Face à une erreur de course : ne pas partager ; en faire une valeur
  `Sendable` ; l'isoler dans un acteur ; seulement ensuite `Mutex` / `Atomic`.
- Les globales sont la source la plus fréquente : `let`, puis `@MainActor`,
  puis `Mutex`, puis `nonisolated(unsafe)`.

## Tâches structurées

- `async let` pour un nombre fixe d'enfants ; `withTaskGroup` pour un nombre
  variable (itérer les résultats au fil de l'eau) ; `withDiscardingTaskGroup`
  quand les enfants ne renvoient rien.
- `Task { }` seulement quand la durée de vie ne tient pas dans un bloc ;
  `Task.detached` presque jamais.
- L'annulation est coopérative : vérifier `Task.isCancelled` ou
  `Task.checkCancellation()` avant un travail coûteux.
- Borner la concurrence au lieu d'un enfant par élément d'une liste sans fin.
- Les continuations se reprennent **exactement une fois** sur chaque chemin.
- `AsyncStream` pour adapter une API à rappels.

## SwiftUI

- `View` est isolée sur l'acteur principal, son `@State` aussi.
- Certaines fermetures tournent hors du fil principal (`visualEffect`,
  `Shape.path(in:)`, `Layout`, `onGeometryChange`) : on y copie la valeur
  utile dans la liste de capture au lieu d'envoyer `self`.
- Les rappels d'action sont synchrones exprès : le changement d'état animé
  (`withAnimation`) se fait dans la même image que l'événement ; une `Task`
  seulement pour le travail long qui suit.

## Protocoles et génériques

- Ni classe ni protocole au départ : des types concrets, puis un protocole
  quand du code se répète, puis du générique.
- Une exigence de protocole est un point de personnalisation (répartition
  dynamique) ; une méthode d'extension seule est statique et peut être
  masquée.
- La composition plutôt que l'héritage ; un transtypage forcé est un signal.
- `some P` par défaut ; `any P` pour stocker des types différents — avec son
  coût (types associés effacés, appels opaques à l'optimiseur).

## Conception d'API

- Clarté au point d'usage avant tout ; pas de préfixes ; pas de `get` en tête.
- Le contrôle d'accès documente ; des états impossibles à écrire (setters
  privés, `enum`, identifiants typés).
- Les property wrappers pour une politique d'accès ; les result builders pour
  un DSL ; les macros pour le code que le compilateur pourrait écrire.

## Performance et mémoire

- L'algorithme d'abord (`removeAll(where:)` plutôt que `remove(at:)` en
  boucle), puis Instruments.
- `final` sur les classes non dérivées ; l'optimisation du module entier.
- Les grandes structures copiées souvent : copie à l'écriture.
- `[MonModele]` plutôt que `[any Modele]` quand c'est possible.
- `InlineArray`, `Span` pour un stockage contigu sans risque.
- La durée de vie garantie d'un objet s'arrête à son dernier usage :
  `weak` / `unowned` seulement pour casser un cycle — mieux, ne pas créer le
  cycle.

## Tests

Swift Testing pour les nouveaux tests : `@Test`, `#expect(expression)`,
`try #require(...)` pour s'arrêter et déballer ; des suites en `struct` ;
`@Test(arguments:)` plutôt qu'une boucle ; des traits (`.disabled("raison")`,
`.bug`, `.tags`, `.timeLimit`) ; `withKnownIssue` pour un échec hors de notre
main ; les tests s'exécutent en parallèle et dans un ordre aléatoire. XCTest
reste pour l'automatisation d'interface et les mesures de performance.

## Journalisation

`Logger` (`os`) plutôt que `print` ; les valeurs non numériques sont masquées
par défaut — `privacy: .public` seulement pour ce qui n'est pas personnel ; un
identifiant de corrélation pour retrouver toute l'histoire d'un échec.

## Syntaxe moderne

| Au lieu de | Écrire |
| --- | --- |
| des ternaires imbriqués, une fermeture appelée pour initialiser | des expressions `if` / `switch` |
| `ObservableObject` et `@Published` partout | `@Observable` |
| scruter un objet pour ses changements | `Observations { … }` |
| des calculs d'index de chaîne | les expressions régulières Swift |
| `withUnsafeBufferPointer` | `.span` |
| des noms de tests contorsionnés | des identifiants bruts dans `@Test` |

Vérifier la version de la chaîne d'outils du projet avant d'employer une
nouveauté.
