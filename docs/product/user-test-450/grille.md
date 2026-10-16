# Grille d'observation — test utilisateur LEKA (LEKA-450)

Une grille par séance. Protocole : `docs/product/user-test-450.md`.

**Séance n°** ……  **Date** ……………  **Animateur** ……………………  **Observateur** ……………………

**Testeur** — profil (métier, sans nom ni employeur) : ……………………………………………………

**Appareil / navigateur** : ……………………  **Adresse e-mail du compte** (pour la mesure) : ……………………………

**Chemin choisi** : ☐ Connecter une source (laquelle : ……………)  ☐ Explorer la démo  ☐ Les deux

## Chronologie

| Repère | Heure |
|---|---|
| Consigne lue (début) | |
| « J'ai ma réponse » / abandon / 30 min | |
| Fin réelle | |

## Événements

Types : **H** hésitation (arrêt > 5 s, retour en arrière) · **E** erreur (ne mène pas où voulu) ·
**I** incompréhension (mot, écran ou réponse mal compris) · **B** blocage (ne peut pas continuer seul) ·
**P** positif (ce qui marche et qu'elle remarque)

| # | Heure | Étape | Écran (adresse) | Type | Ce qui se passe | Ce que la personne dit |
|---|---|---|---|---|---|---|
| 1 | | | | | | |
| 2 | | | | | | |
| 3 | | | | | | |
| 4 | | | | | | |
| 5 | | | | | | |
| 6 | | | | | | |
| 7 | | | | | | |
| 8 | | | | | | |
| 9 | | | | | | |
| 10 | | | | | | |
| 11 | | | | | | |
| 12 | | | | | | |
| 13 | | | | | | |
| 14 | | | | | | |
| 15 | | | | | | |

Étapes : inscription · confirmation de l'e-mail · workspace · source ou démo · question · réponse

## Les réponses de LEKA

| # | Heure | Question posée | Répond à la question ? | Sur des éléments réels ? | La personne la juge utile ? |
|---|---|---|---|---|---|
| 1 | | | ☐ oui ☐ non | ☐ oui ☐ non | ☐ oui ☐ non |
| 2 | | | ☐ oui ☐ non | ☐ oui ☐ non | ☐ oui ☐ non |
| 3 | | | ☐ oui ☐ non | ☐ oui ☐ non | ☐ oui ☐ non |

La **première réponse utile** est la première ligne à trois « oui ».

## Après l'arrêt

1. « Qu'est-ce qui a été le plus difficile ? » ……………………………………………………………………
2. « La réponse que tu as eue, tu en ferais quoi ? » ……………………………………………………………

## Mesure (sur le serveur, après la séance)

```
docker exec leka-api-1 python -m leka.ops.first_answer <adresse du compte>
```

Coller la sortie ici :

```

```
