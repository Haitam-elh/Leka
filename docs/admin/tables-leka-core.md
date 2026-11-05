# Annexe : les 118 tables de LEKA CORE et leurs relations

Générée depuis les modèles SQLAlchemy du dépôt (`main` au 2026-11-05, commit `717a2e10`) : la liste est exacte à cette date. Chaque table a un identifiant `id` (UUID), `created_at` et `updated_at`. « Espace » signifie que la table porte `workspace_id` : ses lignes appartiennent à une organisation cliente, sont supprimées avec elle, et ne se lisent qu'à l'intérieur de son périmètre (voir le rapport, § 3). La colonne « Relations » donne les clés étrangères autres que `workspace_id`.

| Domaine | Module | Tables |
| --- | --- | --- |
| Organisations et membres | `leka/platform` | 3 |
| Comptes et sessions | `leka/identity` | 3 |
| Facturation Stripe | `leka/billing` | 5 |
| Consommation et crédits | `leka/metering` | 3 |
| Gouvernance, rôles, audit, formules | `leka/governance` | 12 |
| Agents, capacités, exécutions, modèles | `leka/capabilities` | 22 |
| Intentions, décisions, plans | `leka/intentions` | 15 |
| Intégrations (sources) | `leka/connectors` | 4 |
| Surveillance et alertes | `leka/monitoring` | 5 |
| Notifications | `leka/notifications` | 4 |
| Bus d'événements et tâches de fond | `leka/background` | 2 |
| Contextes envoyés aux modèles | `leka/context` | 6 |
| Analyses et qualité | `leka/intelligence` | 8 |
| Modèle de l'entreprise (entités, relations) | `leka/knowledge` | 9 |
| Collecte et traitement des données des sources | `leka/ingestion` | 17 |
| **Total** | | **118** |

## Organisations et membres (`leka/platform`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `invitations` | Une invitation à rejoindre une organisation, envoyée à une adresse : rôle, statut, expiration, qui a invité. | oui | `invited_by_user_id` → `users` |
| `memberships` | Le siège d'une personne dans une organisation, avec son rôle. | oui | `user_id` → `users` |
| `workspaces` | Une organisation cliente (le « tenant ») : nom, slug, statut, suspension, demande de suppression, démo, réglages, langue. | non | aucune autre |

## Comptes et sessions (`leka/identity`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `email_tokens` | Un jeton à usage unique envoyé par e-mail : confirmer une adresse ou réinitialiser un mot de passe. | non | `user_id` → `users` |
| `sessions` | Un navigateur connecté : compte, organisation active, dernière activité, expiration, révocation, navigateur, préfixe IP. Purgée à l'expiration. | non | `active_workspace_id` → `workspaces`, `user_id` → `users` |
| `users` | Une personne qui peut se connecter : e-mail, mot de passe haché, adresse confirmée, dernière connexion, échecs de connexion, profil (nom, entreprise, poste, taille d'entreprise, langue, région). | non | aucune autre |

## Facturation Stripe (`leka/billing`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `add_on_checkouts` | Un paiement Stripe d'une option (agent ou bundle) lancé depuis LEKA : qui l'a demandé, pour quelle intention, son statut. | oui | aucune autre |
| `agent_entitlements` | Le droit d'une organisation à un agent ou un bundle : origine (achat, formule, contrat, attribution par LEKA), abonnement Stripe, période, qui et pourquoi. | oui | aucune autre |
| `billing_accounts` | Le compte de facturation Stripe d'une organisation : client, abonnement, formule, cadence, statut, fin de période, résiliation prévue, offre de lancement utilisée, dernière facture. | oui | aucune autre |
| `site_events` | Une vue ou un clic sur la page Tarifs du site, anonyme : page, formule, cadence, langue. | non | aucune autre |
| `stripe_events` | Chaque webhook Stripe reçu, une seule fois : type, organisation concernée, ce qui en a été fait. | non | `for_workspace_id` → `workspaces` |

## Consommation et crédits (`leka/metering`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `credit_prompt_dismissals` | Une invitation à changer de formule écartée par une personne (« Plus tard », « Fermer ») pour un seuil et un mois. | oui | `user_id` → `users` |
| `credit_warnings` | Un seuil de crédits du mois franchi, signalé une fois aux propriétaires et administrateurs de l'organisation. | oui | aucune autre |
| `usage_records` | La consommation d'une exécution : qui, quoi, résultat, durée, appels, échecs, nouvelles tentatives, tokens, coût du modèle, coût LEKA, coût client, modèles et tarifs utilisés. | oui | `user_id` → `users` |

## Gouvernance, rôles, audit, formules (`leka/governance`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `access_decisions` | Une décision d'accès : qui a voulu faire quoi, sur quoi, autorisé ou non, par quelle règle. Ajout seulement : la base refuse de la modifier. | oui | `user_id` → `users` |
| `ai_control_events` | Ce qu'un contrôle de l'IA a fait une fois : sur quel travail, pour qui, sur quel modèle, ce qu'il a trouvé (jamais le texte lui-même). Ajout seulement : la base refuse de la modifier. | oui | `user_id` → `users` |
| `ai_controls` | Un contrôle de l'IA d'une organisation : accès aux modèles, limite d'usage, vérification des réponses, approbation. | oui | `created_by` → `users` |
| `audit_events` | Une ligne du journal d'audit : qui (une personne, son rôle, ou LEKA) a fait quoi, sur quoi, avec quel résultat, d'où. Ajout seulement : la base refuse de la modifier. | oui | `actor_id` → `users` |
| `audit_settings` | La durée de conservation du journal d'audit d'une organisation ; sans ligne, la valeur par défaut. | oui | `updated_by` → `users` |
| `credit_packs` | Des crédits ajoutés à un mois (achetés, ou convenus avec LEKA) en plus de la formule ; perdus à la fin du mois. | oui | aucune autre |
| `entity_restrictions` | Une entité du modèle de l'entreprise réservée aux administrateurs : pourquoi, par qui, depuis quand. | oui | `restricted_by` → `users` |
| `governance_events` | Un changement des rôles ou des politiques d'une organisation : quoi, qui, quand, avant et après. Ajout seulement : la base refuse de la modifier. | oui | `by` → `users` |
| `role_assignments` | Un rôle propre à l'organisation donné à une personne, en plus du rôle de base de son siège. | oui | `assigned_by` → `users`, `role_id` → `workspace_roles`, `user_id` → `users` |
| `workspace_plans` | Une formule attribuée à une organisation : depuis quand, par qui chez LEKA, pourquoi ; la dernière fait foi, aucune vaut Free. Porte les crédits mensuels d'un contrat Enterprise. | oui | aucune autre |
| `workspace_policies` | Une règle de l'organisation : pour ces actions, ces rôles, ces ressources, refuser ou autoriser par exception, avec une priorité. | oui | `created_by` → `users` |
| `workspace_roles` | Un rôle propre à l'organisation : un rôle de base (membre ou administrateur) avec des permissions ajoutées et retirées. | oui | `created_by` → `users` |

## Agents, capacités, exécutions, modèles (`leka/capabilities`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `agent_run_events` | Une étape d'une exécution d'agent : mise en file, contexte, outil appelé ou refusé, réponse du modèle, fin. Ajout seulement : la base refuse de la modifier. | oui | `run_id` → `agent_runs` |
| `agent_runs` | Une exécution d'un agent : lequel, quelle version, demandée par qui, pour quelle intention, sur quel contexte ; statut, livrable, modèle, erreur, horaires. | oui | `requested_by` → `users` |
| `capability_events` | Un fait du catalogue des capacités : enregistrée, changée de cycle de vie, remplacée, refusée. Ajout seulement : la base refuse de la modifier. | non | aucune autre |
| `capability_favourites` | Une capacité gardée sous la main par une personne (« Mes capacités »). | oui | `user_id` → `users` |
| `capability_registrations` | Une version d'une capacité (agent, skill, workflow) telle qu'enregistrée au catalogue de LEKA, commun à tous les clients. | non | aucune autre |
| `capability_routings` | Le choix des capacités pour une intention, et pourquoi : candidates et scores, écartées et pourquoi. | oui | `routed_by` → `users` |
| `capability_suggestions` | Un agent ou un skill qu'un client aimerait voir, envoyé à l'équipe LEKA ; son statut est suivi par l'équipe. | oui | `user_id` → `users` |
| `code_changes` | Une modification de code proposée par un agent : fichiers et différences, décision d'une personne, branche, pull request, CI, déploiement. LEKA ne fusionne jamais. | oui | `decided_by` → `users`, `proposed_by` → `users`, `reverts` → `code_changes`, `source_id` → `sources` |
| `dedicated_agents` | Un agent fait pour une organisation, attribué par LEKA depuis le serveur, jamais acheté. | oui | aucune autre |
| `interface_words` | L'interface traduite par le modèle de LEKA dans une langue sans dictionnaire : une ligne par langue, commune à tous les clients. | non | aucune autre |
| `llm_runs` | Un travail fait par un modèle de langage pour LEKA : finalité, résultat, fournisseur, modèle, appels, tokens, coût, durée. | oui | aucune autre |
| `model_asks` | Ce que LEKA a déjà demandé à un modèle sur un sujet et sur quels faits, pour ne jamais payer deux fois la même question. | oui | aucune autre |
| `model_calls` | Un appel à un modèle de langage : finalité, fournisseur, modèle, tokens, coût en dollars, latence, statut, personne. | oui | `rate_id` → `model_rates`, `user_id` → `users` |
| `model_rates` | Le prix d'un modèle pour LEKA à partir d'un jour, par million de tokens, commun à tous les clients. Jamais réécrit : la base le refuse. | non | aucune autre |
| `publications` | Ce que LEKA propose de publier depuis un livrable (tickets Jira, pages Confluence) : décision d'une personne, résultat. | oui | `decided_by` → `users`, `proposed_by` → `users`, `source_id` → `sources` |
| `skill_runs` | Une exécution d'un skill : lequel, quelle version, appelé par quoi, pour qui, résultat, durée. | oui | `run_by` → `users` |
| `workflow_run_events` | Ce qui s'est passé dans une exécution de workflow, dans l'ordre. Ajout seulement : la base refuse de la modifier. | oui | `run_id` → `workflow_runs` |
| `workflow_run_steps` | Une étape d'une exécution de workflow : statut, tentatives, résultat, raison d'un échec ou d'un saut. | oui | `run_id` → `workflow_runs` |
| `workflow_runs` | Une exécution d'un workflow : lequel, quelle version, demandée par qui, pour quelle intention ; statut, étape en échec, relances. | oui | `requested_by` → `users` |
| `workspace_capabilities` | L'activation d'une capacité par une organisation : activée ou non, et pourquoi. | oui | `changed_by` → `users` |
| `workspace_model_defaults` | Le modèle de LEKA qui répond en premier dans une organisation, choisi par son administrateur. | oui | `changed_by` → `users` |
| `workspace_models` | Le modèle de langage propre d'une organisation, utilisé avant celui de LEKA : clé chiffrée, exclusif ou non, dernier test. | oui | `changed_by` → `users` |

## Intentions, décisions, plans (`leka/intentions`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `action_endpoints` | Un système du client par lequel LEKA est autorisé à agir (un point d'accès https) : actions et environnements acceptés, secret de signature chiffré. | oui | `created_by` → `users` |
| `approval_delegations` | Le pouvoir d'approuver prêté à un autre membre : période, risque maximal, raison. | oui | `delegated_by` → `users`, `delegated_to` → `users`, `revoked_by` → `users` |
| `decision_governance_events` | Un changement de la gouvernance des décisions : politique, exception, délégation, escalade. Ajout seulement : la base refuse de la modifier. | oui | `by` → `users` |
| `governance_exceptions` | Un gel ou une dérogation accordés par un administrateur : sur quoi, période, raison. | oui | `granted_by` → `users`, `revoked_by` → `users` |
| `intention_analyses` | Une analyse d'une intention : capacités choisies et pourquoi, ce que chacune a fait, le résultat et ses preuves. | oui | `intention_id` → `intentions`, `requested_by` → `users` |
| `intention_attachments` | Un fichier joint à une intention : stocké hors base, avec le texte qui en a été lu. | oui | `intention_id` → `intentions`, `uploaded_by` → `users` |
| `intention_decision_votes` | Le vote d'une personne sur une décision : approuver, refuser, modifier, demander des changements. Ajout seulement : la base refuse de la modifier. | oui | `by` → `users`, `decision_id` → `intention_decisions`, `on_behalf_of` → `users` |
| `intention_decisions` | La décision sur ce qu'une intention propose de faire : actions, risque, approbations requises, statut. | oui | `asked_by` → `users`, `intention_id` → `intentions` |
| `intention_events` | Un fait arrivé à une intention : changement de statut, par qui, pourquoi. Ajout seulement : la base refuse de la modifier. | oui | `by` → `users`, `intention_id` → `intentions` |
| `intention_links` | Ce sur quoi une intention s'appuie, ou ce qui en est sorti. | oui | `intention_id` → `intentions`, `linked_by` → `users` |
| `intention_plan_events` | Un fait arrivé à un plan : créé, vérifié, lancé, étape exécutée, confirmé, échoué, annulé. Ajout seulement : la base refuse de la modifier. | oui | `by` → `users`, `plan_id` → `intention_plans` |
| `intention_plan_steps` | Une action d'un plan : quoi, sur quoi, où, exécutée par qui, comment, avec ses preuves. | oui | `plan_id` → `intention_plans` |
| `intention_plans` | Ce qu'une décision approuvée devient : étapes, horaire, vérifications préalables, déroulement. | oui | `created_by` → `users`, `decision_id` → `intention_decisions`, `intention_id` → `intentions`, `started_by` → `users` |
| `intention_verifications` | La vérification que ce qui a été fait a donné le résultat attendu, et son verdict. | oui | `concluded_by` → `users`, `intention_id` → `intentions`, `plan_id` → `intention_plans` |
| `intentions` | Ce qu'une personne a demandé à LEKA : texte, type, statut, compréhension, auteur, contexte, archivage. | oui | `context_id` → `contexts`, `created_by` → `users` |

## Intégrations (sources) (`leka/connectors`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `source_credentials` | Le secret d'une source, chiffré ; supprimé avec elle. | oui | `source_id` → `sources` |
| `source_events` | Un fait arrivé à une source : créée, testée, modifiée, par qui. Ajout seulement (tenu par le code). | oui | `actor_user_id` → `users` |
| `source_settings` | Une version des règles de périmètre et de correspondance d'une source. | oui | `created_by` → `users`, `source_id` → `sources` |
| `sources` | Une connexion configurée à un outil du client : type, nom, statut, santé, dernière erreur, dernière synchronisation. | oui | `created_by` → `users` |

## Surveillance et alertes (`leka/monitoring`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `monitoring_alert_deliveries` | Un envoi d'alerte : quelle règle, quelle alerte, par quel canal, à qui, réussi ou non. | oui | `alert_id` → `monitoring_alerts`, `rule_id` → `monitoring_alert_rules` |
| `monitoring_alert_rules` | Une règle « préviens-moi quand ça va mal » : sur quoi, quels problèmes, quelle gravité, à qui, par quel canal. | oui | aucune autre |
| `monitoring_alerts` | Une alerte ouverte par la surveillance de LEKA chez le client : sujet, gravité, statut, prise en charge, résolution. | oui | aucune autre |
| `monitoring_channel_endpoints` | Un canal d'alerte branché par webhook (Slack, Teams, Discord) : adresse chiffrée, état. | oui | `created_by` → `users` |
| `night_reviews` | Une revue de nuit : ce que LEKA a parcouru et les points à regarder qu'il a trouvés. | oui | `asked_by` → `users` |

## Notifications (`leka/notifications`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `notification_cursors` | Jusqu'où les faits d'une famille ont été lus pour en faire des notifications, et les échecs de lecture. | oui | aucune autre |
| `notification_preferences` | Les catégories de notifications qu'une personne ne veut pas voir dans l'application. | oui | `user_id` → `users` |
| `notification_reads` | Une notification lue par une personne, et quand. | oui | `notification_id` → `notifications`, `user_id` → `users` |
| `notifications` | Une notification de l'application : catégorie, gravité, destinataire (une personne ou une permission), lien. | oui | `audience_user_id` → `users` |

## Bus d'événements et tâches de fond (`leka/background`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `events` | Un fait survenu dans l'organisation d'un client, publié sur le bus d'événements, avec son état de distribution. | oui | aucune autre |
| `job_runs` | Une tâche de fond et tout ce qui lui est arrivé : file, tentatives, statut, erreur, horaires. | non | `event_id` → `events`, `for_workspace_id` → `events`, `for_workspace_id` → `workspaces` |

## Contextes envoyés aux modèles (`leka/context`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `context_checks` | Un recalcul d'un contexte : pourquoi, par qui, après quels changements, avec quel résultat. | oui | `checked_by` → `users`, `context_id` → `contexts` |
| `context_elements` | Un élément (entité, relation) d'une version de contexte, avec sa provenance et sa pertinence. | oui | `version_id` → `context_versions` |
| `context_feedback` | L'avis d'une personne sur un élément d'un contexte : utile, inutile, faux, ou manquant. | oui | `context_id` → `contexts`, `given_by` → `users` |
| `context_follows` | Jusqu'à quelle construction du modèle les contextes d'une organisation ont été suivis. | oui | aucune autre |
| `context_versions` | Une version assemblée d'un contexte : quand, depuis quelle construction du modèle, ce qu'elle contient, sa qualité. Jamais modifiée. | oui | `assembled_by` → `users`, `context_id` → `contexts` |
| `contexts` | Le contexte d'une demande : à quoi il sert, ce qu'il demande, sa vie. | oui | `created_by` → `users` |

## Analyses et qualité (`leka/intelligence`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `authority_rules` | Le crédit qu'une organisation donne à une source sur un attribut : à préférer ou à éviter. | oui | `created_by` → `users`, `source_id` → `sources` |
| `enrichment_candidates` | Un enrichissement du modèle proposé par une analyse, gardé jusqu'à la décision d'une personne. | oui | `decided_by` → `users` |
| `intelligence_findings` | Une conclusion d'une analyse sur une chose, suivie d'un passage à l'autre. | oui | aucune autre |
| `intelligence_runs` | Une analyse d'une organisation par LEKA : pourquoi, depuis quoi, avec quel résultat. | oui | `requested_by` → `users` |
| `intelligence_steps` | Une analyse d'un passage : version, durée, résultat, ou pourquoi elle n'a pas abouti. | oui | `run_id` → `intelligence_runs` |
| `knowledge_conflicts` | Un désaccord entre les sources du client sur une chose : chaque version, et la recommandation de LEKA. | oui | aucune autre |
| `quality_history` | Un point de l'historique d'un score de qualité, écrit quand il bouge ; gardé un an. | oui | aucune autre |
| `quality_scores` | Le score de confiance actuel de ce que LEKA sait d'une chose ou d'un domaine, et ce qui le fait baisser. | oui | aucune autre |

## Modèle de l'entreprise (entités, relations) (`leka/knowledge`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `entities` | Une chose réelle de l'entreprise du client (service, équipe, personne, incident, dépôt…) : type, nom, attributs, cycle de vie, provenance. | oui | aucune autre |
| `entity_versions` | Une version d'une entité : son historique. | oui | `entity_id` → `entities`, `run_id` → `model_runs` |
| `model_assertions` | Un fait sur le modèle de l'entreprise proposé par LEKA et validé, par une personne ou par la politique de l'organisation. | oui | aucune autre |
| `model_operations` | Un changement contrôlé du modèle de l'entreprise demandé par quelqu'un : qui, quand, pourquoi, résultat. | oui | `requested_by` → `users`, `undone_by` → `users` |
| `model_runs` | Une construction du modèle de l'entreprise d'une organisation. | oui | aucune autre |
| `model_snapshots` | Ce que le modèle de l'entreprise contenait à un moment : volumes par type, qualité. | oui | `run_id` → `model_runs` |
| `relationship_changes` | Une relation apparue, modifiée ou disparue lors d'une construction du modèle : l'historique des relations. Ajout seulement (tenu par le code). | oui | `run_id` → `model_runs` |
| `relationship_issues` | Ce que la dernière construction du modèle a trouvé d'anormal dans une relation. | oui | `run_id` → `model_runs` |
| `relationships` | Une relation orientée entre deux entités d'une même organisation. | oui | `from_entity_id` → `entities`, `to_entity_id` → `entities` |

## Collecte et traitement des données des sources (`leka/ingestion`)

| Table | Rôle | Espace | Relations (colonne → table) |
| --- | --- | --- | --- |
| `enriched_relationships` | Une relation entre deux entités résolues, dite par une source ou déduite par une règle, avec sa confiance et ses preuves. | oui | `run_id` → `enrichment_runs` |
| `enrichment_runs` | Un passage d'enrichissement sur une organisation : quand, depuis quelle résolution, ce qu'il a ajouté, ses échecs. | oui | aucune autre |
| `entity_enrichments` | Un attribut ajouté à une entité résolue par une règle d'enrichissement, avec sa confiance et ses preuves. | oui | `run_id` → `enrichment_runs` |
| `extracted_records` | Ce que l'extraction a tiré d'un enregistrement indexé, ou pourquoi rien. | oui | `source_id` → `sources`, `source_record_id` → `source_records` |
| `normalised_records` | Les candidats issus de la normalisation d'un enregistrement : entité, personnes, services, équipes, relations. | oui | `parsed_record_id` → `parsed_records`, `source_id` → `sources` |
| `parsed_records` | Ce que l'analyse syntaxique a lu dans une extraction : faits, confiance, preuves, ou pourquoi rien. | oui | `extracted_record_id` → `extracted_records`, `source_id` → `sources` |
| `processing_runs` | Un passage d'une étape de traitement sur une source. | oui | `source_id` → `sources` |
| `raw_payloads` | Une donnée brute récupérée chez un client, stockée hors base (S3), avec son expiration. | oui | `source_id` → `sources` |
| `resolution_decisions` | Une décision de la résolution d'entités : fusion, lien probable ou ambiguïté, avec sa règle et ses preuves. | oui | `entity_id` → `resolved_entities`, `other_entity_id` → `resolved_entities` |
| `resolution_runs` | Un passage de résolution d'entités sur une organisation. | oui | aucune autre |
| `resolved_entities` | Une chose réelle telle que les sources du client la montrent, après résolution : la matière du modèle de l'entreprise. | oui | aucune autre |
| `resolved_keys` | Une clé sous laquelle une entité résolue est connue dans une source : sa provenance. | oui | `entity_id` → `resolved_entities`, `source_id` → `sources` |
| `source_records` | L'index de ce que LEKA a vu d'un objet d'une source (dépôt, commit, ticket…). | oui | `last_seen_run_id` → `sync_runs`, `source_id` → `sources` |
| `source_syncs` | L'avancement de la lecture d'une capacité d'une source et l'état de son dernier passage, échecs consécutifs compris. | oui | `source_id` → `sources` |
| `sync_runs` | Un passage de synchronisation sur une source, du début à la fin : volumes, erreur. | oui | `source_id` → `sources` |
| `validated_records` | Ce que la validation a trouvé d'un enregistrement normalisé : statut, problèmes, qualité. | oui | `normalised_record_id` → `normalised_records`, `run_id` → `processing_runs`, `source_id` → `sources` |
| `webhook_deliveries` | Une livraison reçue par une source à webhook, signée : statut, volume, traitement. | oui | `run_id` → `sync_runs`, `source_id` → `sources` |
