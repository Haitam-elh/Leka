# Les indicateurs du tableau de bord de LEKA ADMIN (LEKA-548)

`GET /api/v1/admin/overview` calcule chaque chiffre de l'accueil de LEKA ADMIN à partir des données réelles de LEKA CORE. Le code est dans `api/leka/admin/overview.py`, et cette page en est la définition : un chiffre qui change de règle change ici aussi.

## 1. Les règles communes

- **La période** : `today` (depuis minuit UTC), `7d`, `30d` (par défaut), `90d`, `12m`, ou `custom` avec `from` et `to` (deux ans au plus). Chaque chiffre « de la période » compte ce qui s'est passé entre son début (inclus) et sa fin (exclue). Les chiffres « maintenant » (MRR, formules, sources en erreur, incidents) ne dépendent pas de la période.
- **Les séries** ont un point par jour jusqu'à 92 jours de période, et un point par mois au-delà. Les jours et les mois sont comptés en UTC. Un jour sans événement vaut 0 : c'est un vrai zéro.
- **Hors démonstration** : les organisations de démonstration (LEKA-449) sont exclues de tous les chiffres, de même que tout ce qui leur appartient.
- **Stripe** : un événement Stripe qui n'appartient à aucune organisation de LEKA (un événement de test, un autre usage du compte Stripe), ou que LEKA n'a pas appliqué, n'est jamais compté.
- **Inconnu n'est jamais zéro** : un chiffre que LEKA ne peut pas établir vaut `null` dans l'API, et l'appli dit pourquoi (« Pas encore mesuré », « Non renseigné », « Réservé à la Finance »…). Un taux sans base (aucune intention terminée, aucune organisation active) vaut `null`, jamais 0 %.
- **Les montants** (MRR, ARR, encaissé, remboursé, coûts) ne sont rendus qu'à un rôle qui lit la facturation (`billing:read` : Super Admin et Finance par défaut). Pour les autres rôles, ils valent `null` et `amounts_granted` vaut `false`. Les comptes, eux, restent visibles : abonnements, paiements échoués.

## 2. Acquisition

| Indicateur | Champ | Règle |
| --- | --- | --- |
| Clients | `organisations` | les organisations, maintenant |
| Nouveaux clients | `organisations_new` | créées dans la période (`workspaces.created_at`) |
| Utilisateurs | `users` | les personnes inscrites, maintenant |
| Nouveaux utilisateurs | `users_new` | inscrites dans la période (`users.created_at`) |
| Par formule | `by_plan` | la formule actuelle de chaque organisation : la dernière attribuée (`workspace_plans`), Free si aucune |
| Free, payant | `organisations_free`, `organisations_paid` | sur la formule Free ; sur toute autre formule, payée par Stripe ou non (un contrat Enterprise, un compte de l'équipe LEKA) |

## 3. Activité

| Indicateur | Champ | Règle |
| --- | --- | --- |
| DAU, WAU, MAU | `dau`, `wau`, `mau` | les personnes vues dans le produit aujourd'hui (UTC), sur les 7 et sur les 30 derniers jours. « Vue » : une session utilisée ce jour-là (`user.active` du journal d'activité, une fois par personne et par jour) |
| Organisations actives | `organisations_active` | celles où quelqu'un a été vu, ou a demandé une intention, dans la période |
| Intentions lancées | `intentions_created` | demandées dans la période |
| Intentions terminées, échouées | `intentions_completed`, `intentions_failed` | passées au statut terminé, ou échoué, dans la période |
| Taux de réussite des intentions | `intention_success_rate` | terminées ÷ (terminées + échouées). Une intention annulée ou refusée n'entre pas dans le calcul |
| Analyses terminées, échouées | `analyses_completed`, `analyses_failed` | analyses (`intention_analyses`) finies dans la période : avec un résultat entier, partiel ou non concluant ; ou en échec. Une analyse « bloquée » pose une question au client et une analyse « arrêtée » l'a été par une personne : elles ne sont ni terminées ni échouées |

## 4. Business : revenus, encaissements, abonnements

Trois notions distinctes, jamais additionnées entre elles :

1. **Le revenu récurrent (MRR, ARR)**, maintenant, hors taxes : ce que les abonnements en cours rapportent chaque mois.
2. **L'encaissé** de la période, taxes comprises : l'argent réellement reçu par les factures payées.
3. **Les coûts** de la période (§ 6) : ce que LEKA paie à ses fournisseurs.

| Indicateur | Champ | Règle |
| --- | --- | --- |
| MRR | `mrr` | la somme, pour chaque abonnement Stripe payant (`active` ou `past_due`), de son prix récurrent ramené au mois. Prix récurrent : le prix catalogue de chaque ligne multiplié par la quantité, moins le coupon tant qu'il dure (l'offre de lancement : 20 % pendant 12 mois), hors TVA. Un prix annuel compte pour un douzième par mois. Une option achetée (agent, pack) compte une fois par abonnement, même si elle ouvre plusieurs agents. En euros |
| ARR | `arr` | le MRR multiplié par 12 |
| Abonnements comptés | `mrr_subscriptions` | les abonnements payants dont le prix est connu, donc dans le MRR |
| Prix inconnu | `mrr_unknown` | les abonnements payants dont LEKA ne connaît pas le prix : souscrits avant LEKA-548, tant que `python -m leka.billing.cli amounts` ne l'a pas lu chez Stripe, ou dont le prix n'est pas un montant fixe (par paliers, à l'usage). Quand il y en a, le MRR est un minimum, et l'appli le dit. Tous inconnus : `mrr` vaut `null` |
| En essai | `trialing` | les abonnements en période d'essai : pas encore un revenu, donc hors MRR |
| Payants hors Stripe | `paid_outside_stripe` | les organisations sur une formule payante sans abonnement Stripe payant (contrat, compte de l'équipe LEKA) : hors MRR, faute de montant connu de LEKA |
| Encaissé | `collected` | la somme des factures payées dans la période (`invoice.paid`, `amount_paid`), TVA comprise. Ce n'est pas un revenu récurrent : une facture annuelle est encaissée en une fois |
| Dont TVA | `collected_tax` | la TVA comprise dans l'encaissé |
| Factures sans montant | `collected_unknown` | les factures payées de la période dont LEKA n'a pas gardé le montant (reçues avant LEKA-548). Toutes sans montant : `collected` vaut `null` |
| Remboursé | `refunded` | la somme des remboursements de la période (`charge.refunded`) |
| Nouveaux abonnements | `subscriptions_started` | abonnements Stripe créés et appliqués dans la période |
| Résiliations | `subscriptions_canceled` | abonnements Stripe terminés dans la période |
| Churn | `churn_rate` | résiliations de la période ÷ abonnements payants à son début. Le nombre au début se déduit : payants maintenant − nouveaux de la période + résiliés de la période. `null` sans aucun abonnement au début |
| Paiements échoués | `payments_failed` | factures dont le paiement a échoué dans la période (`invoice.payment_failed`) |
| Organisations payantes | `paying_organisations` | celles dont l'abonnement Stripe garde la formule maintenant : `active`, `trialing` ou `past_due` |

D'où viennent les montants :
- **Le prix d'un abonnement** est lu dans l'abonnement que Stripe envoie à chacun de ses événements, et gardé à côté de son état : `billing_accounts.recurring` pour la formule, `agent_entitlements.recurring` pour une option (voir `api/leka/billing/revenue.py`).
- **Les montants d'une facture ou d'un remboursement** sont gardés avec l'événement Stripe (`stripe_events.detail` : `amount`, `currency`, `tax`).
- **Pour les abonnements souscrits avant LEKA-548**, `python -m leka.billing.cli amounts` lit leur prix une fois chez Stripe, en lecture seule. Les factures déjà reçues restent sans montant : la facturation complète, avec son historique, vient avec LEKA-554.

## 5. Produit

| Indicateur | Champ | Règle |
| --- | --- | --- |
| Exécutions d'agents | `agent_runs` | lancées dans la période |
| Taux de réussite des agents | `agent_success_rate` | réussies ÷ (réussies + échouées) |
| Agents utilisés | `agents_used` | agents distincts lancés dans la période |
| Organisations utilisatrices | `organisations_running_agents` | celles qui ont lancé au moins un agent dans la période |
| Adoption des agents | `agent_adoption_rate` | parmi les organisations actives (§ 3), la part qui a lancé un agent |
| Agents les plus utilisés | `top_agents` | les cinq agents les plus lancés dans la période, avec leurs réussites et leurs échecs |
| Consommation IA | `credits_consumed` | les crédits consommés dans la période : le coût des modèles de LEKA divisé par la valeur d'un crédit. `null` si aucun coût n'a pu être mesuré |

## 6. Coûts

| Indicateur | Champ | Règle |
| --- | --- | --- |
| Coût IA | `costs.ai_usd` | ce que les modèles de LEKA ont coûté à LEKA dans la période (`usage_records.leka_cost_usd`), en dollars US, au tarif en vigueur. Le modèle propre d'une organisation n'y est pas : c'est son coût, pas celui de LEKA |
| Exécutions au coût incomplet | `costs.ai_incomplete` | celles dont le coût n'est connu qu'en partie, ou pas du tout : le coût IA est alors un minimum |
| Infrastructure | `costs.infrastructure_usd` | non mesuré par LEKA (toujours `null`) |

Les crédits consommés (§ 5) et le coût IA ont la même base : ce sont deux unités différentes, jamais additionnées.

## 7. Technique

| Indicateur | Champ | Règle |
| --- | --- | --- |
| Incidents actifs | `incidents` | les alertes d'exploitation qui sonnent maintenant (`leka/ops/alerts.py` : tâches non exécutées, planificateur arrêté, modèles en échec, sauvegardes en retard…), avec leur gravité et depuis quand, telles que la surveillance les a jugées à son dernier passage (toutes les 5 minutes). `null` quand Redis, où elles sont gardées, ne répond pas : jamais une liste vide dans ce cas |
| Intégrations en erreur | `sources_in_error` | les sources en statut d'erreur, ou dont la santé est mauvaise, maintenant |
| Synchronisations échouées | `sync_failures` | dans la période |
| Traitements en échec | `jobs_failed` | tâches de fond échouées dans la période |

## 8. Activité récente

`recent` : les huit derniers événements de chaque famille, quelle que soit la période, avec le nom de l'organisation :
- inscriptions et organisations créées ;
- abonnements souscrits, modifiés ou résiliés, paiements échoués et remboursements ;
- intentions demandées ou échouées.

Les incidents en cours sont ceux du § 7. Leur historique (ouvert, résolu) viendra avec LEKA-556.

## 9. Préparation Customer Intelligence

Calculé quand les données existent, et dit inconnu sinon. Le Health Score prédictif et la prédiction du churn sont hors MVP.

| Indicateur | Champ | Règle |
| --- | --- | --- |
| Cohorte de la période | `organisations_created` | les organisations créées dans la période : les chiffres suivants portent sur elles |
| Activation | `activated`, `activation_rate` | celles qui ont eu une intention terminée depuis leur création, et leur part |
| Time to First Value | `time_to_first_value_hours` | la médiane, en heures, du temps entre la création d'une organisation et sa première intention terminée, sur celles qui en ont eu une |
| Conversion Free vers payant | `converted`, `conversion_rate` | celles qui ont souscrit un abonnement Stripe depuis leur création, et leur part |
| Rétention par cohorte | `retention` | pour chacun des six derniers mois d'inscription : le nombre de personnes inscrites ce mois-là, puis, pour chacun des cinq mois suivants, la part d'entre elles vue dans le produit ce mois-là. Le mois en cours compte ce qui a été vu jusqu'ici. Un mois pas encore venu, ou antérieur au début du suivi de l'activité, vaut `null` |
| Début du suivi | `tracked_since` | la première activité (`user.active`) enregistrée par LEKA : avant, la rétention n'est pas connue |

## 10. Les séries

| Série | Valeur par jour (ou par mois) |
| --- | --- |
| `organisations` | les organisations au total, à la fin du jour |
| `users` | les personnes au total, à la fin du jour |
| `users_new` | les inscriptions du jour |
| `users_active` | les personnes vues ce jour-là (par mois : vues dans le mois), à partir du début du suivi |
| `intentions_created` | les intentions demandées |
| `credits_consumed` | les crédits consommés |
| `mrr` | le MRR tel qu'il était ce jour-là (par mois : le dernier jour connu du mois), gardé par la tâche du journal d'activité toutes les 5 minutes dans `admin_daily_figures`. Il commence le jour où LEKA-548 est déployé. Seulement pour un rôle qui lit la facturation |
