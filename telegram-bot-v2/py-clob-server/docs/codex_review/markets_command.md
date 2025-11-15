# /markets – Cartographie du flux

## Vue d'ensemble
- Point d'entrée `markets_command` (`telegram-bot-v2/py-clob-server/telegram_bot/handlers/trading_handlers.py:76`) déclenché par `/markets`.
- Objectif : afficher un carrousel de 10 marchés (groupés par évènement si possible), proposer des filtres et préparer le contexte pour l'achat rapide.
- Le pipeline repose sur `MarketDataLayer` pour lire `subsquid_markets_poll` avec cache Redis et retombe sur `MarketDatabase` (PostgreSQL `markets`) en dernier recours.
- Les interactions aval (sélection, achat) passent par des callbacks Telegram (`filter_*`, `event_select_*`, `market_select_*`, `quick_buy_*`) orchestrés dans `callback_handlers`.

## Parcours utilisateur
- `/markets` → message de chargement puis liste paginée avec boutons de filtres et numéros. Chaque item montre volume + échéance (`_build_markets_ui`, `trading_handlers.py:370`).
- Boutons de filtre (volume/liquidity/newest/endingsoon) renvoient à `handle_market_filter_callback` (`callback_handlers.py:2812`) qui recharge la page en conservant le contexte session.
- Si un item correspond à un évènement multi-issues, le bouton mène à `handle_event_select_callback` (`callback_handlers.py:2936`) affichant les sous-marchés avec prix YES/NO et pagination locale.
- Sélection d’un marché → `handle_market_select_callback` (`callback_handlers.py:2426`), affichage détail (prix, échéance, solde utilisateur) + boutons `Buy YES/NO`.
- Choix YES/NO → `handle_buy_prompt_callback` (`callback_handlers.py:2680`) qui stocke l’intention dans la session et affiche options $5/$10/$20/custom.
- Bouton montant → `handle_quick_buy_callback` (`telegram_bot-v2/py-clob-server/telegram_bot/handlers/callbacks/buy_callbacks.py:56`) menant à un écran de confirmation.
- Confirmation (`confirm_order_*`) → `TradingService.execute_buy` (`telegram_bot-v2/py-clob-server/telegram_bot/services/trading_service.py:369`) qui exécute l’ordre via CLOB et persiste la transaction.

## Chaîne d'appel & responsabilités clés
- `markets_command` :
  - Initialise la session (`SessionManager.init_user`, `session_manager.py:50`), remet le filtre `volume`.
  - Charge `MarketDataLayer.get_high_volume_markets_page` (`core/services/market_data_layer.py:95`) avec `group_by_events=True`.
  - Alimente `_build_markets_ui` pour structurer texte + clavier.
- `MarketDataLayer` :
  - Tente cache Redis (`RedisPriceCache.get_markets_page`, `core/services/redis_price_cache.py:728`).
  - Fait du paging direct sur `subsquid_markets_poll` (`_get_markets_subsquid_poll_page`, `core/services/market_data_layer.py:235`), filtre `status == 'ACTIVE'`, `end_date > now`, contrôle qualité `_is_market_valid` (`core/services/market_data_layer.py:580`).
  - Groupe les marchés via événements (`_group_markets_by_events`, `core/services/market_data_layer.py:620`) en s’appuyant sur la colonne JSONB `events`.
- Callbacks UI :
  - Filtrage `filter_*` réutilise `_get_filtered_markets` (`trading_handlers.py:239`) qui redirige vers les variantes `MarketDataLayer.get_*_page`.
  - `event_select_*` fait appel à `MarketDatabase.get_markets_in_event` (`market_database.py:191`) + `MarketGroupingService.format_group_for_display` (`core/services/market_grouping_service.py:88`). Un cache mémoire `MarketGroupCache` (`core/services/market_group_cache.py:12`) stocke la liste d’IDs pour les événements slug.
  - `market_select_*` appelle `MarketService.get_market_by_id` (`telegram_bot-v2/py-clob-server/telegram_bot/services/market_service.py:41`) avec hiérarchie Redis → `subsquid_markets_poll` → `markets`.
- Achat :
  - `TradingService.execute_buy` vérifie la readiness du wallet utilisateur (`user_service.is_wallet_ready`, `users` table via `database.py:52`), consulte le solde on-chain (`balance_checker.check_usdc_balance`, `core/services/balance_checker.py:60`).
  - Utilise `UserTrader.speed_buy` (CLOB client) puis loggue dans `transactions` (`database.py:218`) via `TransactionService.log_trade` (`telegram_bot-v2/py-clob-server/telegram_bot/services/transaction_service.py:35`) et déclenche collecte de frais (`fees` table, `database.py:262`).
  - Invalidation de caches positions (`RedisPriceCache.invalidate_user_positions`, `core/services/redis_price_cache.py:836`) et planification de collecte de fees en tâche asynchrone.

## Sources de données & écritures
| Étape | Stockage / service | Champs clefs (lecture) | Écriture ? |
| --- | --- | --- | --- |
| Listing initial | Table `subsquid_markets_poll` (`database.py:940`) | `market_id`, `status`, `volume`, `liquidity`, `end_date`, `events`, `outcome_prices`, `tradeable` | Non |
| Fallback listing | Table `markets` (`database.py:737`) via `MarketDatabase` | `id`, `question`, `volume`, `end_date`, `event_id`, `outcome_prices` | Non |
| Event drilldown | `markets` + cache mémoire `MarketGroupCache` (`core/services/market_group_cache.py:12`) | même champs + `event_title` | Cache mémoire mis à jour |
| Sélection marché | Redis (`RedisPriceCache.get_market_data`, `core/services/redis_price_cache.py:420`), `subsquid_markets_poll`, `markets` | `tradeable`, `outcome_prices`, `events` | Cache Redis TTL 60s |
| Vérif wallet | Table `users` (`database.py:37`) | `polygon_address`, flags d’approbation | Non |
| Exécution achat | CLOB (API externe), `transactions`, `fees` | `market_id`, `outcome`, `tokens`, `price_per_token`, `fee_amount` | Oui (`transactions`, `fees`), invalidation caches |

## Gestion de session & contexte
- `SessionManager` stocke `market_filter`, `market_filter_page`, `current_market`, `pending_order`, `return_page` (`session_manager.py:70`).
- Lors d’un `market_select`, le marché complet est placé dans `session['current_market']` pour alimenter les étapes suivantes (`callback_handlers.py:2490`).
- Les callbacks d’achat écrivent `pending_order` avec `market_id`, `side`, `price`, `return_page` (`callback_handlers.py:2725`) puis `handle_quick_buy_callback` relit cet état (`buy_callbacks.py:69`).

## Caching & performance
- Redis : pages listées (`markets:{filter}:page:{n}`) TTL 10 min (`redis_price_cache.py:694`), marché individuel (`market:{id}`) TTL 60s (`redis_price_cache.py:354`), positions utilisateur invalidées post-trade.
- Cache mémoire court terme pour groupements (`MarketGroupCache`, TTL 60s).
- `MarketDataLayer` surdimensionne la requête (x5) avant regroupement pour limiter les trous lorsque plusieurs marchés appartiennent au même événement (`market_data_layer.py:120`).

## Points de vigilance & dettes
- **Fallback silencieux** : en cas d’exception, `markets_command` retourne une liste mais n’édite jamais `loading_msg` (`trading_handlers.py:151`). L’utilisateur reste bloqué sur “Loading...” → nécessite un `edit_text` de secours.
- **Divergence `tradeable`** : `MarketService.get_market_by_id` exige `tradeable == True` (`market_service.py:82`). Si `MarketDataLayer` renvoie un marché `ACTIVE` mais pas encore flaggé `tradeable`, la sélection échoue (“Market not found”). Vérifier cohérence du pipeline d’ingestion.
- **Groupements slug fallback** : `MarketRepository.get_markets_by_event` avertit que la recherche slug sans cache est fragile (`market_repository.py:735`). S’assurer que `MarketGroupCache` est toujours alimenté pour éviter résultats vides.
- **Validation agressive** : `_is_market_valid` exclut toute valeur prix <1¢ ou >99¢ (`market_data_layer.py:601`), ce qui peut masquer des marchés très polarisés mais toujours actifs.
- **Logs volumineux** : `MarketService.get_market_by_id` loggue le dict complet (`market_service.py:113`), bruit potentiellement inutile en production.

## Recommandations / next steps
- Ajouter un chemin d’affichage fallback en cas d’erreur (message d’erreur + options navigables).
- Harmoniser critères `tradeable` côté listing et sélection (soit filtrer en amont, soit relaxer la vérification).
- Monitorer les métriques cache (hits/misses loggués dans `redis_price_cache.py:743`) pour détecter dérives.
- Prévoir tests d’intégration (simulation /markets → quick buy) pour valider que `pending_order`/`pending_confirmation` sont toujours cohérents, surtout après custom amount (`buy_callbacks.py:108`).
