# 🔄 Redémarrer l'API pour Activer les Nouveaux Endpoints

## Problème

L'API est en cours d'exécution mais ne contient pas les nouveaux endpoints :
- `GET /api/v1/wallet/balance/telegram/{telegram_user_id}`
- `POST /api/v1/trades/`

## Solution : Redémarrer l'API

### Option 1 : Utiliser le script de démarrage

```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild

# Arrêter l'API actuelle
pkill -f api_only.py

# Redémarrer avec le script
./scripts/dev/start-api.sh
```

### Option 2 : Redémarrer manuellement

```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild

# Arrêter l'API
pkill -f api_only.py

# Attendre quelques secondes
sleep 2

# Redémarrer
python api_only.py
```

### Option 3 : Redémarrer tous les services

```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild

# Arrêter tous les services
./scripts/dev/stop-all.sh

# Redémarrer tous les services
./scripts/dev/start-all.sh
```

## Vérification

Après redémarrage, vérifiez que les nouveaux endpoints sont disponibles :

```bash
# Vérifier l'endpoint balance
curl "http://localhost:8000/api/v1/wallet/balance/telegram/6500527972" | jq .

# Vérifier l'endpoint trades (dry run)
curl -X POST "http://localhost:8000/api/v1/trades/" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 6500527972,
    "market_id": "23656",
    "outcome": "Yes",
    "amount_usd": 2.0,
    "dry_run": true
  }' | jq .

# Vérifier dans Swagger UI
open http://localhost:8000/docs
```

## Résultat Attendu

### Balance Endpoint

```json
{
  "user_id": 1,
  "telegram_user_id": 6500527972,
  "polygon_address": "0x7d47DBe915A48eE5fE1E13B35BAe76c9daed718a",
  "solana_address": "9x84oqzGHF3GkN1KUe47TQi277LgT1Sz398fzpQHcLXM",
  "polygon_balance": 15.46,
  "solana_balance": 0.0,
  "usdc_balance": 15.46,
  "pol_balance": 2.92,
  "stage": "ready"
}
```

### Trades Endpoint (Dry Run)

```json
{
  "success": true,
  "status": "executed",
  "order_id": "dry_run_6500527972_23656_YES",
  "tokens": 1.9,
  "price": 0.55,
  "total_cost": 2.0,
  "transaction_hash": "dry_run_tx_6500527972",
  "market_title": "Super Bowl Champion 2026 (DRY RUN)",
  "dry_run": true
}
```

## Notes

- La balance devrait maintenant afficher **15.46 USDC.e** au lieu de 0.00
- Le service de balance fonctionne correctement (testé directement)
- Le problème était que l'API n'avait pas été redémarrée avec les nouveaux endpoints
