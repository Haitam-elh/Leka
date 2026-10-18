---
titre: La bibliothèque de design de LEKA
description: L'index des guides du designer de LEKA — lequel ouvrir selon la demande (revue, animations, audit, performance, pire des cas, téléphone, React Native, directions de design, bibliothèques, notifications, vocabulaire, Swift).
---

# La bibliothèque de design de LEKA

Les guides que lisent le designer (`design-review`), la revue des animations
(`motion-review`), la revue de qualité d'interface (`ui-quality-review`) et la
modification de code quand elle touche une interface (`code-change`). Ils
s'ouvrent un à un avec `read_method`, au moment où l'agent en a besoin.

| Guide | Quand l'ouvrir |
| --- | --- |
| `principes.md` | toujours d'abord : le format d'un constat, quand et comment animer, les composants, les gestes, la performance, l'accessibilité, la liste de contrôle |
| `directions.md` | proposer un nouveau design : deux ou trois directions sur des axes nommés, dessinées par le simulateur |
| `revue-animations.md` | juger les animations d'un écran ou d'une pull request (Bloquer / Approuver) |
| `audit-mouvement.md` | auditer tout le mouvement d'une application et écrire des plans de correction |
| `opportunites-animation.md` | trouver où animer — et où ne pas animer |
| `construire-animation.md` | écrire une animation : la séquence de décisions et les recettes |
| `performance-animation.md` | une animation qui saccade : le diagnostic et les remèdes |
| `pire-des-cas.md` | casser un écran avec des données réelles défavorables, et le catalogue des valeurs |
| `telephone-web.md` | une application web qui doit se sentir native sur téléphone |
| `interfaces-fluides.md` | les gestes, les ressorts, les matières, la typographie, les principes de conception |
| `react-native.md` | le mouvement dans une application React Native ou Expo |
| `bibliotheques.md` | la bonne bibliothèque pour un besoin d'interface |
| `notifications-sonner.md` | les notifications avec Sonner |
| `vocabulaire-mouvement.md` | mettre le mot juste sur un effet |
| `swift.md` | relire ou proposer du Swift et du SwiftUI |

Ces guides sont écrits pour LEKA : un agent lit le code d'un dépôt connecté,
ne voit pas l'écran rendu, ne modifie rien lui-même. Ce qu'il propose de
changer, il le donne en code exact ; LEKA dessine les écrans qu'il propose et,
avec l'accord d'une personne, ouvre la pull request.
