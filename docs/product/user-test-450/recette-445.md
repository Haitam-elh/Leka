# Recette fonctionnelle de l'onboarding (LEKA-445) — avant le test utilisateur

Critère 1 de LEKA-450 : Karim fait cette recette **avant** la séance, et note
ses retours dans le ticket. Chaque ligne se coche ✅ (conforme), ❌ (défaut,
décrit dans « Retours ») ou — (non applicable).

**Environnement** : production, `https://leka-core.com`, avec une adresse
e-mail jamais utilisée sur LEKA. Navigateur en navigation privée, puis la même
chose sur un téléphone (au moins les étapes A à D).

Date : ……………… Navigateur / appareil : ………………………… Adresse utilisée : ………………………

## A. Inscription

- [ ] Depuis l'accueil du site, « Se connecter » puis « Créer un compte » mène à l'inscription, sans chercher.
- [ ] Le formulaire dit ce qu'il attend (nom, e-mail, mot de passe et sa règle) avant l'erreur.
- [ ] Une erreur de saisie (e-mail invalide, mot de passe trop court, adresse déjà utilisée) dit quoi corriger.
- [ ] Après validation, l'écran dit qu'un e-mail de confirmation a été envoyé, et à quelle adresse.

## B. Confirmation de l'e-mail

- [ ] L'e-mail arrive en moins de 2 minutes, pas dans les indésirables (noter s'il y tombe).
- [ ] Son expéditeur, son objet et son texte sont clairs, en français.
- [ ] Le lien ouvre LEKA, confirme l'adresse et connecte la personne (ou dit clairement de se connecter).
- [ ] Un lien déjà utilisé ou expiré dit quoi faire.

## C. Bienvenue et premier workspace

- [ ] L'écran de bienvenue explique en une phrase ce que LEKA fait, sans jargon interne (modules, agents, architecture).
- [ ] Il propose clairement deux chemins : **Connecter une source** ou **Explorer la démo**.
- [ ] Le workspace créé porte un nom compréhensible (modifiable dans les paramètres).

## D. Premiers pas (sur l'accueil)

- [ ] La carte « Premiers pas » apparaît, au-dessus de la zone de question, sans la cacher.
- [ ] Elle montre l'état réel du workspace, et chaque état se voit :
  - [ ] **vide** — rien de connecté ;
  - [ ] **connecté** — une source ajoutée, pas encore lue ;
  - [ ] **synchronisation en cours** — une première lecture en cours ;
  - [ ] **en échec** — avec la cause connue et l'action pour corriger ;
  - [ ] **prêt** — au moins une source lue.
- [ ] La carte peut être fermée ; l'accueil reste utilisable sans elle (non bloquant).
- [ ] Elle disparaît d'elle-même une fois une source lue et une première question posée.
- [ ] Une question libre peut être posée à tout moment, même sans source.

## E. Explorer la démo

- [ ] « Explorer la démo » ouvre l'environnement de démonstration (Nova Retail) en un clic.
- [ ] **Chaque page** de la démo dit qu'on est dans la démo, avec des données fictives.
- [ ] Les données de démo n'apparaissent jamais dans le workspace réel de la personne.
- [ ] On sort de la démo en un clic, vers son workspace ou vers la connexion d'une source.
- [ ] Les exemples de questions proposés dans la démo s'appliquent à Nova Retail.

## F. Connecter une source

- [ ] « Connecter une source » mène à l'assistant d'ajout, avec les outils proposés.
- [ ] Une connexion réussie le dit, et la première lecture démarre.
- [ ] Une connexion en échec (mauvais jeton, droits manquants) dit **la cause** et **l'action** pour corriger.
- [ ] Ce qui est connecté, ce qui reste à connecter et la couverture sont visibles (Mon environnement › Sources).

## G. Première question et première analyse

- [ ] Les exemples de questions suivent ce qui est réellement lu (questions sur le code si une source de code est lue) ; tant que rien n'est lu, ils sont présentés comme des exemples.
- [ ] Une question libre peut être posée ; LEKA la reformule ou demande une précision si besoin, sans bloquer.
- [ ] Une analyse est livrée, sur des éléments réels (la source ou la démo), avec ce sur quoi elle s'appuie.
- [ ] Si l'analyse demande un agent payant ou plus de capacité, la page le dit avec son prix, sans rien acheter sans confirmation.

## H. Mesure (à faire une fois la recette finie)

Sur le serveur, avec l'adresse utilisée :

```
docker exec leka-api-1 python -m leka.ops.first_answer <adresse>
```

- [ ] Chaque étape faite pendant la recette a une heure (inscription, confirmation, workspace, source ou démo, question, réponse).

## Retours

| # | Étape | Écran | Défaut constaté | Gravité (bloquant / majeur / mineur) |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

**Verdict** : ☐ prêt pour le test utilisateur  ☐ à corriger d'abord (les défauts bloquants)

À copier dans LEKA-450 une fois remplie.
