# Les indicateurs de LEKA ADMIN (LEKA-548, LEKA-554, LEKA-555, LEKA-556)

`GET /api/v1/admin/overview` calcule chaque chiffre de l'accueil de LEKA ADMIN à partir des données réelles de LEKA CORE. Le code est dans `api/leka/admin/overview.py`, et cette page en est la définition : un chiffre qui change de règle change ici aussi. Le module Facturation & Finance (`GET /api/v1/admin/billing/finance`, `api/leka/admin/billing.py`) a ses règles au § 11.

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
- **Pour les abonnements souscrits avant LEKA-548**, `python -m leka.billing.cli amounts` lit leur prix une fois chez Stripe, en lecture seule. Les factures reçues avant LEKA-554 restent sans montant ici ; leur historique complet se lit au § 11, après `python -m leka.billing.cli history`.

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

## 11. Facturation & Finance (LEKA-554)

`GET /api/v1/admin/billing/finance` (`billing:read`) calcule les chiffres du module Facturation & Finance. Ce qu'ils lisent est gardé par `api/leka/billing/history.py`, à chaque événement Stripe vérifié.

**Stripe est la source de vérité.** Chaque ligne gardée est ce que Stripe a dit en dernier, jamais un chiffre de LEKA. **Aucune donnée de carte n'est gardée** : ni numéro, ni marque, ni quatre derniers chiffres, ni empreinte.

Trois notions, jamais additionnées entre elles :

1. **Le revenu récurrent**, hors TVA : le MRR maintenant (§ 4) et ce qui l'a fait bouger pendant la période.
2. **La facturation**, TVA comprise : ce que les factures émises dans la période demandent, proratas compris.
3. **L'encaissement**, TVA comprise : ce que les paiements ont pris, moins ce que les remboursements ont rendu.

Les règles communes du § 1 s'appliquent : période, organisations de démonstration exclues, montants réservés à `billing:read`. Les montants sont en euros. Un montant dit dans une autre devise est compté dans `other_currencies`, jamais converti.

### Ce qui est gardé

| Table | Écrite par | Règle |
| --- | --- | --- |
| `billing_invoices` | les événements `invoice.*`, et `python -m leka.billing.cli history` | une ligne par facture Stripe, telle que Stripe l'a dite en dernier : statut, montants, remise, TVA, proratas, lignes, période, dates, tentatives, lien vers sa page Stripe. Un événement plus ancien que celui qui l'a écrite ne change rien |
| `billing_payments` | `invoice.paid`, `invoice.payment_failed` | un paiement réussi par facture payée (référence `<facture>:paid`), une tentative échouée par événement, avec sa prochaine tentative. Écrit une fois |
| `billing_refunds` | `charge.refunded`, et `history` | une ligne par paiement remboursé : `amount` est tout ce qu'il a rendu (deux remboursements partiels font une ligne, leur somme), `at` la date du dernier |
| `billing_subscription_changes` | `checkout.session.completed`, `customer.subscription.*`, pour la formule et pour chaque agent ou bundle acheté seul | une ligne par événement qui change ce qui compte, avec la formule, le statut et le MRR avant et après. Écrite une fois |

### Les changements d'un abonnement

Un abonnement **rapporte** quand il est `active` ou `past_due` (Stripe relance, la formule tient). Un essai (`trialing`) ne rapporte rien encore. Il est **terminé** quand il est `canceled`, `unpaid` ou `incomplete_expired`.

| Type | Règle |
| --- | --- |
| `trial` | il entre en essai |
| `new` | il se met à rapporter sans avoir été terminé avant : une souscription, ou un essai converti |
| `reactivation` | il se met à rapporter après avoir été terminé |
| `churn` | il cesse de rapporter |
| `upgrade`, `downgrade` | il rapporte avant et après, et son MRR monte ou baisse. Si l'un des deux MRR n'est pas connu : selon le rang de la formule (Free, Starter, Growth, Business, Enterprise) |
| `interval` | même MRR, autre périodicité |
| `renewal_off`, `renewal_on` | la résiliation en fin de période est demandée, ou annulée. Le MRR ne bouge pas tant qu'il rapporte |

### Les indicateurs

| Indicateur | Champ | Règle |
| --- | --- | --- |
| MRR, ARR | `mrr`, `arr` | comme au § 4, maintenant |
| Abonnements, prix inconnu, en essai | `subscriptions`, `unknown_prices`, `trialing` | comme au § 4 (`mrr_subscriptions`, `mrr_unknown`, `trialing`) |
| MRR au début | `mrr_start` | le MRR gardé à la fin du jour qui précède la période (`admin_daily_figures`, § 10). `null` avant le début du suivi |
| Nouveaux, réactivations, hausses, baisses, churn | `new`, `reactivations`, `upgrades`, `downgrades`, `churn` | les changements de la période de chaque type : `count` leur nombre, `eur` leur effet sur le MRR (nouveau, réactivation : le MRR d'après ; churn : le MRR d'avant ; hausse, baisse : l'écart), `unknown` ceux dont le montant n'est pas connu, laissés de côté |
| MRR expliqué | `mrr_explained` | MRR au début + nouveaux + réactivations + hausses − baisses − churn, les changements comptés depuis minuit du premier jour. Seulement pour une période qui finit maintenant, sinon `null` |
| Écart | `mrr_gap` | MRR − MRR expliqué : ce qu'aucun changement n'explique (un coupon arrivé à sa fin, un abonnement dont le prix n'était pas encore connu). 0 quand tout est expliqué |
| Par formule | `by_plan` | les abonnements qui rapportent, par formule, et `add_ons` pour les agents et bundles achetés seuls (chaque abonnement une fois) : leur nombre, leur MRR, ceux au prix inconnu. La somme de leurs MRR est le MRR |
| Facturé | `invoiced`, `invoices` | les factures émises dans la période (`open`, `paid` ou `uncollectible` ; un brouillon ou une facture annulée ne compte pas) : leur total, TVA comprise |
| Dont TVA | `invoiced_tax` | la TVA de ces factures |
| Proratas | `prorations` | la somme de leurs lignes de prorata : ce qu'un changement en cours de période a facturé (positif) ou crédité (négatif) |
| Factures ouvertes | `open_invoices`, `open_amount` | maintenant : les factures en attente de paiement, et ce qui reste à payer |
| Encaissé | `payments_succeeded`, `collected` | les factures payées dans la période, et ce qu'elles ont pris, TVA comprise |
| Paiements échoués | `payments_failed`, `failed_amount` | chaque tentative échouée de la période, et ce qu'elle demandait |
| Remboursé | `refunds`, `refunded` | les paiements remboursés dans la période, et ce qu'ils ont rendu |
| Encaissé net | `net_collected` | encaissé − remboursé |
| Autres devises | `other_currencies` | les factures, paiements et remboursements de la période dans une autre devise que l'euro |
| Événements Stripe | `events`, `last_event_at` | ceux reçus dans la période, par issue (`applied`, `ignored`, `failed`) ; le dernier reçu |
| En échec | `failed_events` | maintenant : les événements dont l'application a échoué et qu'aucune livraison n'a encore appliqués |
| Non rattachés | `unlinked_events` | ceux de la période d'un client Stripe que LEKA ne connaît pas |

### Les proratas

- **Un changement de formule ou de périodicité** dans le portail est immédiat et proratisé : Stripe facture la différence maintenant, ou la crédite sur la prochaine facture (`docs/pricing.md`).
- **Le MRR suit le nouveau prix** dès l'événement `customer.subscription.updated` : c'est un changement `upgrade` ou `downgrade`.
- **Le prorata est de la facturation**, jamais du revenu récurrent : il apparaît dans les lignes de la facture (`proration: true`) et dans `prorations`, jamais dans le MRR.
- **Un coupon** est retiré du MRR tant qu'il dure (§ 4). Quand il finit, le MRR monte sans événement : l'écart le montre.
- **Une facture annuelle** compte entière dans le facturé et l'encaissé, et pour un douzième par mois dans le MRR.

### Réconcilier avec Stripe

Deux commandes, sur le serveur, en lecture seule chez Stripe :

- **`python -m leka.billing.cli history [--since AAAA-MM-JJ] [--organisation ID]`** lit chez Stripe chaque facture et chaque paiement remboursé des clients que LEKA connaît, et les garde comme Stripe les dit maintenant. C'est ce que les webhooks ont manqué, et l'historique d'avant LEKA-554. La relancer n'écrit rien deux fois.
- **`python -m leka.billing.cli reconcile [--organisation ID]`** met chaque abonnement compté par LEKA (formule et options) à côté de celui de Stripe : statut, formule, MRR, et le MRR des deux côtés. Chaque écart est listé, rien n'est corrigé : l'état d'un abonnement reste celui du webhook. Elle sort avec le code 1 s'il y a un écart.

### Les erreurs de synchronisation

Un événement dont l'application échoue est annulé en entier, puis gardé `failed` avec son erreur (`detail.error`, `detail.message`) et le nombre de tentatives (`detail.attempts`). Stripe le redélivre pendant trois jours. La livraison qui réussit l'applique, une fois, et garde le nombre de tentatives. Un événement en échec se voit dans LEKA ADMIN (Événements Stripe, filtre « En échec ») et dans `failed_events`. Un événement d'un client inconnu est gardé `ignored`, sans organisation, et compté dans `unlinked_events`.

## 12. Environnements & Intégrations (LEKA-555)

`GET /api/v1/admin/environments/…` (`environments:read`, `api/leka/admin/environments.py`) lit ce que LEKA CORE sait des environnements de ses clients : leurs sources et leurs lectures (`sources`, `sync_runs`), et ce que le modèle de l'entreprise en a tiré (`entities`, `relationships`). Jamais un chiffre à part, jamais un identifiant de connexion ni un réglage de source.

### L'état d'une source et d'un environnement

| État | Règle |
| --- | --- |
| En erreur | une source en erreur (`status` `error`), non saine (`health` `unhealthy`), ou dont la dernière lecture a échoué (`sync_status` `failed`) |
| Dégradé | aucune en erreur, une dégradée (`status` ou `health` `degraded`) |
| Non à jour | aucune en erreur ni dégradée, une source active non lue depuis 3 heures, ou jamais lue. Les sources sont lues toutes les heures : trois lectures manquées, ce qu'elle disait n'est plus ce qui est (la règle du jumeau numérique) |
| À jour | toutes ses sources actives lues dans les 3 heures, saines |
| Aucune source | rien de connecté, hors sources désactivées |

L'état d'un environnement est le pire de ses sources, les désactivées mises à part. Une source est **vérifiée** quand elle est active, saine et a été lue au moins une fois.

### Les erreurs

L'erreur d'une source ou d'une lecture est son **diagnostic** : un code (`AUTH_INVALID`, `AUTH_EXPIRED`, `PERMISSION_DENIED`, `INSUFFICIENT_SCOPE`, `NOT_FOUND`, `RATE_LIMITED`, `TIMEOUT`, `NETWORK_UNREACHABLE`, `PROVIDER_ERROR`, `CONFIG_INVALID`, `UNSUPPORTED`, `UNKNOWN`), ce qui s'est passé, ce qu'il faut faire, si réessayer peut suffire, le statut HTTP du fournisseur. Il est nettoyé des secrets quand il est écrit (`leka.connectors.errors`), et passé de nouveau au détecteur de LEKA (`leka.core.sensitive`) avant d'être rendu.

### Les relations

| Certitude | Règle |
| --- | --- |
| Confirmée | affirmée par les enregistrements d'une source (`origin` `stated`), ou proposée par LEKA puis validée par une personne (`accepted`, LEKA-380) |
| Supposée | déduite par une règle d'enrichissement (`inferred`), avec sa règle et sa confiance. Jamais présentée comme certaine |
| Inconnue | un service ou une application reliés à rien : on ne sait pas de quoi ils dépendent |

La **cartographie** reprend l'architecture que le client voit dans « Mon environnement » (`leka.knowledge`, toutes les cartes). Elle ne montre que les relations que le modèle tient, donc étayées par les données collectées, entre deux éléments affichés. Chaque relation dit les sources qui l'affirment, sa règle, sa confiance et sa preuve (passée au détecteur de secrets). La **fraîcheur** est la date de la dernière construction du modèle et celle de la dernière lecture de chaque source ; la **provenance** est la source de chaque élément et de chaque relation.

## 13. Incidents & notifications (LEKA-556)

`api/leka/admin/incidents.py`. Une surveillance tourne toutes les 5 minutes, juste après le journal d'activité. Elle ouvre les incidents à partir de ce que LEKA CORE enregistre déjà, jamais d'un chiffre à part. Chaque incident nomme son organisation ; aucune, quand c'est la plateforme elle-même. Les organisations de démonstration sont mises à part.

### Les catégories

| Catégorie | Ouvert par | Un incident par | Résolu par LEKA quand |
| --- | --- | --- | --- |
| Intentions échouées (`intention_failed`) | une intention passée en échec (journal d'activité) | intention | elle se termine finalement |
| Agents en erreur (`agent_failed`) | une exécution d'agent échouée | organisation et agent | l'agent réussit de nouveau chez elle |
| Erreurs API (`api_error`) | une requête qui échoue du côté de LEKA (une 500), gardée par l'API (`leka.ops.api_errors`) : sa route déclarée, jamais ses valeurs, le type d'erreur, l'identifiant de requête, l'organisation quand la requête la connaît | route, type d'erreur et organisation | une personne le résout |
| Intégrations déconnectées (`integration_disconnected`) | une source en erreur ou non saine | source | elle redevient saine |
| Synchronisations échouées (`sync_failed`) | une lecture échouée | source | elle est relue avec succès |
| Problèmes de crédits (`credits`) | les crédits du mois épuisés | organisation et mois | ils ne le sont plus |
| Paiements échoués (`payment_failed`) | une tentative de paiement échouée (LEKA-554) | facture | la facture est payée ou annulée |
| Plateforme (`platform`) | une règle de la surveillance des opérations (LEKA-408) | règle | elle ne se déclenche plus |
| Erreurs récurrentes | un incident vu 3 fois en 24 heures, quelle que soit sa catégorie : dit récurrent (`recurring`), sa gravité relevée d'un cran, une fois | | |

### Jamais de doublon indu

Un problème a une empreinte (`fingerprint`), unique parmi les incidents ouverts (nouveaux ou en cours). Le même problème ajoute une occurrence à l'incident ouvert. Chaque fait n'est compté qu'une fois, car l'événement qui le dit a sa clé (`dedupe_key`). Un problème qui revient après que son incident a été résolu ou fermé ouvre un nouvel incident, qui nomme le précédent.

### Gravité et statuts

| Gravité | Pour |
| --- | --- |
| Critique | quelqu'un agit maintenant : une règle critique de la plateforme, ou un incident élevé devenu récurrent |
| Élevée | aujourd'hui : erreurs API, intégration déconnectée, paiement échoué, crédits épuisés |
| Moyenne | intention échouée, agent en erreur, synchronisation échouée, règle d'avertissement |
| Faible | réservée à ce qui ne gêne personne |

Les statuts sont `new` (nouveau), `in_progress` (en cours), `resolved` (résolu) et `closed` (fermé). Un incident nouveau ou en cours peut être résolu ou fermé ; un incident résolu peut être repris ou fermé ; un incident fermé l'est pour de bon. LEKA résout lui-même un incident quand son problème a disparu, et le dit dans son historique.

### Les notifications

Chaque notification n'est écrite qu'une fois (sa clé `dedupe_key`), et chaque admin la lit pour soi.

| Notification | Quand |
| --- | --- |
| Incident critique | un incident s'ouvre critique, ou le devient |
| Paiement échoué | un incident de paiement s'ouvre |
| Intégration déconnectée | un incident d'intégration s'ouvre |
| Erreurs répétées | un incident devient récurrent |
| Capacité proche de la limite | les crédits du mois d'une organisation passent le premier seuil d'avertissement (une fois par mois) |
| Consommation anormale | les crédits des dernières 24 heures dépassent 3 fois la journée moyenne des 4 semaines précédentes, et 20 crédits (une fois par jour) |
