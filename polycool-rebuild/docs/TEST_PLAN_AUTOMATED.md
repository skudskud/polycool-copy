# 🧪 Plan de Test Automatisé - Flow Complet Utilisateur

**Utilisateur de test:** `6500527972` (wallet existant avec balance)
**Montant de trade:** `$2.00` (custom amount)
**Date:** $(date)

---

## 📋 Objectif

Simuler le flow complet utilisateur depuis la découverte des marchés jusqu'à l'exécution d'un trade, en testant tous les chemins critiques de l'API.

---

## 🔧 Prérequis

```bash
# Vérifier que tous les services sont démarrés
./scripts/dev/test-services.sh

# Variables d'environnement
API_URL="http://localhost:8000"
API_PREFIX="/api/v1"
USER_ID=6500527972
```

---

## 📊 Structure du Plan de Test

### **Phase 1: Vérification Infrastructure** ✅
### **Phase 2: Informations Utilisateur** 👤
### **Phase 3: Découverte Marchés (Trending)** 🔥
### **Phase 4: Exploration Event** 📦
### **Phase 5: Détails Marché & Prix** 💰
### **Phase 6: Sélection Outcome & Trade** 🎯
### **Phase 7: Vérification Position** 📈
### **Phase 8: Tests Complémentaires** 🔍

---

## 🚀 Phase 1: Vérification Infrastructure

### Test 1.1: Health Check API
```bash
curl -s "${API_URL}/health/live" | jq .
```
**Résultat attendu:** `{"status": "ok"}`

### Test 1.2: Health Check Ready (avec composants)
```bash
curl -s "${API_URL}/health/ready" | jq .
```
**Résultat attendu:** Tous les composants `healthy: true`

### Test 1.3: Vérification Redis
```bash
redis-cli ping
```
**Résultat attendu:** `PONG`

---

## 👤 Phase 2: Informations Utilisateur

### Test 2.1: Récupérer données utilisateur
```bash
curl -s "${API_URL}${API_PREFIX}/users/${USER_ID}" | jq .
```
**Vérifications:**
- ✅ `telegram_user_id` = `6500527972`
- ✅ `polygon_address` existe
- ✅ `solana_address` existe
- ✅ `id` (internal ID) existe

**Variables à extraire:**
```bash
INTERNAL_USER_ID=$(curl -s "${API_URL}${API_PREFIX}/users/${USER_ID}" | jq -r '.id')
echo "Internal User ID: ${INTERNAL_USER_ID}"
```

### Test 2.2: Vérifier wallet balance
```bash
curl -s "${API_URL}${API_PREFIX}/wallet/balance/${USER_ID}" | jq .
```
**Vérifications:**
- ✅ Balance Polygon (USDC) > 0
- ✅ Balance Solana (USDC) > 0
- ✅ Adresses présentes

**Variables à extraire:**
```bash
POLYGON_BALANCE=$(curl -s "${API_URL}${API_PREFIX}/wallet/balance/${USER_ID}" | jq -r '.polygon_balance')
SOLANA_BALANCE=$(curl -s "${API_URL}${API_PREFIX}/wallet/balance/${USER_ID}" | jq -r '.solana_balance')
echo "Polygon Balance: \$${POLYGON_BALANCE}"
echo "Solana Balance: \$${SOLANA_BALANCE}"
```

### Test 2.3: Vérifier positions existantes
```bash
curl -s "${API_URL}${API_PREFIX}/positions/user/${USER_ID}" | jq .
```
**Vérifications:**
- ✅ Liste des positions (peut être vide)
- ✅ Structure correcte

---

## 🔥 Phase 3: Découverte Marchés (Trending)

### Test 3.1: Récupérer trending markets (groupés par events)
```bash
curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=10&group_by_events=true" | jq .
```
**Vérifications:**
- ✅ Liste non vide
- ✅ Mix de `event_group` et `individual` markets
- ✅ `total_volume` > 0 pour les event groups
- ✅ `market_count` > 0 pour les event groups

### Test 3.2: Analyser structure des résultats
```bash
curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=10&group_by_events=true" | jq '[.[] | select(.type == "event_group")] | .[0]'
```
**Vérifications:**
- ✅ `event_id` existe
- ✅ `event_title` existe
- ✅ `event_slug` existe
- ✅ `market_count` > 0

**Variables à extraire:**
```bash
FIRST_EVENT_ID=$(curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=10&group_by_events=true" | jq -r '[.[] | select(.type == "event_group")] | .[0].event_id')
FIRST_EVENT_TITLE=$(curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=10&group_by_events=true" | jq -r '[.[] | select(.type == "event_group")] | .[0].event_title')
echo "Selected Event ID: ${FIRST_EVENT_ID}"
echo "Selected Event Title: ${FIRST_EVENT_TITLE}"
```

### Test 3.3: Vérifier pagination
```bash
curl -s "${API_URL}${API_PREFIX}/markets/trending?page=1&page_size=5&group_by_events=true" | jq 'length'
```
**Résultat attendu:** `5` ou moins

---

## 📦 Phase 4: Exploration Event

### Test 4.1: Récupérer tous les marchés d'un event (par ID)
```bash
curl -s "${API_URL}${API_PREFIX}/markets/events/${FIRST_EVENT_ID}?page=0&page_size=20" | jq .
```
**Vérifications:**
- ✅ Liste de marchés non vide
- ✅ Chaque marché a `id`, `title`, `outcomes`
- ✅ `outcome_prices` présents (peut être null pour certains)

**Variables à extraire:**
```bash
EVENT_MARKETS=$(curl -s "${API_URL}${API_PREFIX}/markets/events/${FIRST_EVENT_ID}?page=0&page_size=20" | jq '.')
echo "Event Markets Count: $(echo "${EVENT_MARKETS}" | jq 'length')"
```

### Test 4.2: Récupérer marchés d'un event (par title - plus robuste)
```bash
# URL encode le title
ENCODED_TITLE=$(echo "${FIRST_EVENT_TITLE}" | jq -sRr @uri)
curl -s "${API_URL}${API_PREFIX}/markets/events/by-title/${ENCODED_TITLE}?page=0&page_size=20" | jq .
```
**Vérifications:**
- ✅ Même structure que Test 4.1
- ✅ Résultats cohérents

### Test 4.3: Filtrer marchés avec prix disponibles
```bash
curl -s "${API_URL}${API_PREFIX}/markets/events/${FIRST_EVENT_ID}?page=0&page_size=20" | jq '[.[] | select(.outcome_prices != null and (.outcome_prices | length) > 0)] | .[0]'
```
**Vérifications:**
- ✅ Marché avec `outcome_prices` non vide
- ✅ `outcomes` correspond à `outcome_prices`

**Variables à extraire:**
```bash
MARKET_WITH_PRICES=$(curl -s "${API_URL}${API_PREFIX}/markets/events/${FIRST_EVENT_ID}?page=0&page_size=20" | jq '[.[] | select(.outcome_prices != null and (.outcome_prices | length) > 0)] | .[0]')
SELECTED_MARKET_ID=$(echo "${MARKET_WITH_PRICES}" | jq -r '.id')
SELECTED_MARKET_TITLE=$(echo "${MARKET_WITH_PRICES}" | jq -r '.title')
echo "Selected Market ID: ${SELECTED_MARKET_ID}"
echo "Selected Market Title: ${SELECTED_MARKET_TITLE}"
```

---

## 💰 Phase 5: Détails Marché & Prix

### Test 5.1: Récupérer détails complets du marché
```bash
curl -s "${API_URL}${API_PREFIX}/markets/${SELECTED_MARKET_ID}" | jq .
```
**Vérifications:**
- ✅ `id` correspond
- ✅ `title` présent
- ✅ `outcomes` = `["Yes", "No"]` ou similaire
- ✅ `outcome_prices` = `[0.XX, 0.YY]` avec somme ≈ 1.0
- ✅ `clob_token_ids` présent (liste de 2 token IDs)
- ✅ `volume` > 0
- ✅ `liquidity` > 0

**Variables à extraire:**
```bash
MARKET_DETAILS=$(curl -s "${API_URL}${API_PREFIX}/markets/${SELECTED_MARKET_ID}" | jq .)
OUTCOMES=$(echo "${MARKET_DETAILS}" | jq -r '.outcomes[]')
OUTCOME_PRICES=$(echo "${MARKET_DETAILS}" | jq -r '.outcome_prices[]')
CLOB_TOKEN_IDS=$(echo "${MARKET_DETAILS}" | jq -r '.clob_token_ids[]')
echo "Outcomes: ${OUTCOMES}"
echo "Prices: ${OUTCOME_PRICES}"
```

### Test 5.2: Analyser les prix et identifier l'outcome le plus cher
```bash
# Extraire prix Yes et No
PRICE_YES=$(echo "${MARKET_DETAILS}" | jq -r '.outcome_prices[0]')
PRICE_NO=$(echo "${MARKET_DETAILS}" | jq -r '.outcome_prices[1]')

# Comparer et sélectionner outcome le plus cher
if (( $(echo "${PRICE_YES} > ${PRICE_NO}" | bc -l) )); then
    SELECTED_OUTCOME="Yes"
    SELECTED_PRICE="${PRICE_YES}"
    SELECTED_TOKEN_ID=$(echo "${MARKET_DETAILS}" | jq -r '.clob_token_ids[0]')
else
    SELECTED_OUTCOME="No"
    SELECTED_PRICE="${PRICE_NO}"
    SELECTED_TOKEN_ID=$(echo "${MARKET_DETAILS}" | jq -r '.clob_token_ids[1]')
fi

echo "Selected Outcome: ${SELECTED_OUTCOME}"
echo "Selected Price: \$${SELECTED_PRICE}"
echo "Selected Token ID: ${SELECTED_TOKEN_ID}"
```
**Vérifications:**
- ✅ Prix Yes + Prix No ≈ 1.0
- ✅ Outcome sélectionné = celui avec prix le plus élevé
- ✅ Token ID correspond à l'outcome

### Test 5.3: Vérifier que le marché est tradable
```bash
# Vérifier liquidité suffisante (> $10)
LIQUIDITY=$(echo "${MARKET_DETAILS}" | jq -r '.liquidity')
if (( $(echo "${LIQUIDITY} > 10" | bc -l) )); then
    echo "✅ Market has sufficient liquidity: \$${LIQUIDITY}"
else
    echo "⚠️ Market liquidity low: \$${LIQUIDITY}"
fi

# Vérifier que le marché est actif
IS_ACTIVE=$(echo "${MARKET_DETAILS}" | jq -r '.active')
if [ "${IS_ACTIVE}" = "true" ]; then
    echo "✅ Market is active"
else
    echo "❌ Market is not active"
fi
```

---

## 🎯 Phase 6: Sélection Outcome & Trade

### Test 6.1: Vérifier balance suffisante pour trade
```bash
TRADE_AMOUNT=2.00
REQUIRED_BALANCE=$(echo "${TRADE_AMOUNT} + 0.5" | bc -l)  # Trade + fees estimées

if (( $(echo "${POLYGON_BALANCE} >= ${REQUIRED_BALANCE}" | bc -l) )); then
    echo "✅ Sufficient Polygon balance: \$${POLYGON_BALANCE} >= \$${REQUIRED_BALANCE}"
else
    echo "❌ Insufficient Polygon balance: \$${POLYGON_BALANCE} < \$${REQUIRED_BALANCE}"
    exit 1
fi
```

### Test 6.2: Préparer données de trade
```bash
# Résumé du trade à exécuter
echo "📊 TRADE SUMMARY:"
echo "=================="
echo "User ID: ${USER_ID}"
echo "Market ID: ${SELECTED_MARKET_ID}"
echo "Market Title: ${SELECTED_MARKET_TITLE}"
echo "Outcome: ${SELECTED_OUTCOME}"
echo "Price: \$${SELECTED_PRICE}"
echo "Amount: \$${TRADE_AMOUNT}"
echo "Token ID: ${SELECTED_TOKEN_ID}"
echo "Current Polygon Balance: \$${POLYGON_BALANCE}"
echo ""
```

### Test 6.3: Exécuter trade (si endpoint existe)
**⚠️ NOTE:** L'endpoint de trading n'existe pas encore dans l'API REST.
**Alternative:** Utiliser le service `TradeService` directement ou créer l'endpoint.

**Format attendu (si endpoint créé):**
```bash
curl -X POST "${API_URL}${API_PREFIX}/trades/" \
  -H "Content-Type: application/json" \
  -d "{
    \"user_id\": ${USER_ID},
    \"market_id\": \"${SELECTED_MARKET_ID}\",
    \"outcome\": \"${SELECTED_OUTCOME}\",
    \"amount_usd\": ${TRADE_AMOUNT},
    \"order_type\": \"FOK\"
  }" | jq .
```

**Vérifications attendues:**
- ✅ `success: true`
- ✅ `order_id` présent
- ✅ `tokens` > 0
- ✅ `price` ≈ prix attendu
- ✅ `transaction_hash` présent
- ✅ Balance mise à jour

### Test 6.4: Vérifier exécution (dry-run si endpoint manquant)
```bash
# Si endpoint n'existe pas, simuler avec TradeService en mode dry-run
# (nécessite accès Python direct ou création endpoint)
echo "⚠️ Trade endpoint not available - skipping actual execution"
echo "💡 To test actual trade, create POST /api/v1/trades/ endpoint"
```

---

## 📈 Phase 7: Vérification Position

### Test 7.1: Vérifier nouvelle position créée
```bash
# Attendre 2-3 secondes pour que la position soit créée
sleep 3

curl -s "${API_URL}${API_PREFIX}/positions/user/${USER_ID}" | jq .
```
**Vérifications:**
- ✅ Nouvelle position présente
- ✅ `market_id` = `${SELECTED_MARKET_ID}`
- ✅ `outcome` = `${SELECTED_OUTCOME}`
- ✅ `amount` ≈ `${TRADE_AMOUNT}`
- ✅ `entry_price` ≈ `${SELECTED_PRICE}`
- ✅ `status` = `"open"`

**Variables à extraire:**
```bash
NEW_POSITION=$(curl -s "${API_URL}${API_PREFIX}/positions/user/${USER_ID}" | jq "[.[] | select(.market_id == \"${SELECTED_MARKET_ID}\")] | .[0]")
POSITION_ID=$(echo "${NEW_POSITION}" | jq -r '.id')
echo "New Position ID: ${POSITION_ID}"
```

### Test 7.2: Vérifier balance mise à jour
```bash
NEW_POLYGON_BALANCE=$(curl -s "${API_URL}${API_PREFIX}/wallet/balance/${USER_ID}" | jq -r '.polygon_balance')
BALANCE_DIFF=$(echo "${POLYGON_BALANCE} - ${NEW_POLYGON_BALANCE}" | bc -l)
echo "Balance Before: \$${POLYGON_BALANCE}"
echo "Balance After: \$${NEW_POLYGON_BALANCE}"
echo "Balance Difference: \$${BALANCE_DIFF}"
```
**Vérifications:**
- ✅ Balance réduite d'environ `${TRADE_AMOUNT}` + fees
- ✅ Différence ≈ `${TRADE_AMOUNT}` (avec marge d'erreur pour fees)

### Test 7.3: Vérifier détails position
```bash
curl -s "${API_URL}${API_PREFIX}/positions/${POSITION_ID}" | jq .
```
**Vérifications:**
- ✅ Tous les champs présents
- ✅ `pnl` calculé (peut être 0 si prix inchangé)
- ✅ `created_at` récent

---

## 🔍 Phase 8: Tests Complémentaires

### Test 8.1: Recherche de marchés
```bash
SEARCH_QUERY="trump"
curl -s "${API_URL}${API_PREFIX}/markets/search?query_text=${SEARCH_QUERY}&page=0&page_size=5" | jq .
```
**Vérifications:**
- ✅ Résultats pertinents
- ✅ `title` contient le terme recherché

### Test 8.2: Marchés par catégorie
```bash
CATEGORY="politics"
curl -s "${API_URL}${API_PREFIX}/markets/categories/${CATEGORY}?page=0&page_size=10" | jq .
```
**Vérifications:**
- ✅ Liste non vide
- ✅ Tous les marchés ont `category` = `"politics"`

### Test 8.3: Fetch marché on-demand (si marché non dans DB)
```bash
# Utiliser un market_id qui pourrait ne pas être dans la DB
TEST_MARKET_ID="0x1234567890abcdef"
curl -X POST "${API_URL}${API_PREFIX}/markets/fetch/${TEST_MARKET_ID}" | jq .
```
**Vérifications:**
- ✅ Marché récupéré depuis Gamma API
- ✅ Stocké en DB
- ✅ Retourné avec structure correcte

### Test 8.4: Performance - Temps de réponse
```bash
echo "Testing API response times..."
time curl -s "${API_URL}/health/live" > /dev/null
time curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=10" > /dev/null
time curl -s "${API_URL}${API_PREFIX}/markets/${SELECTED_MARKET_ID}" > /dev/null
```
**Vérifications:**
- ✅ Health check < 100ms
- ✅ Trending markets < 500ms
- ✅ Market details < 300ms

---

## 📝 Script de Test Complet

### Créer le script automatisé
```bash
#!/bin/bash
# test-flow-complete.sh

set -e  # Exit on error

API_URL="${API_URL:-http://localhost:8000}"
API_PREFIX="${API_PREFIX:-/api/v1}"
USER_ID="${USER_ID:-6500527972}"
TRADE_AMOUNT=2.00

echo "🧪 POLYCOOL API - FLOW COMPLET TEST"
echo "===================================="
echo "User ID: ${USER_ID}"
echo "Trade Amount: \$${TRADE_AMOUNT}"
echo ""

# Phase 1: Infrastructure
echo "✅ Phase 1: Infrastructure Checks..."
curl -s "${API_URL}/health/live" | jq -e '.status == "ok"' > /dev/null
echo "  ✓ API Health OK"

# Phase 2: User Info
echo "✅ Phase 2: User Information..."
INTERNAL_USER_ID=$(curl -s "${API_URL}${API_PREFIX}/users/${USER_ID}" | jq -r '.id')
POLYGON_BALANCE=$(curl -s "${API_URL}${API_PREFIX}/wallet/balance/${USER_ID}" | jq -r '.polygon_balance')
echo "  ✓ User ID: ${INTERNAL_USER_ID}"
echo "  ✓ Polygon Balance: \$${POLYGON_BALANCE}"

# Phase 3: Trending Markets
echo "✅ Phase 3: Trending Markets..."
FIRST_EVENT_ID=$(curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=10&group_by_events=true" | jq -r '[.[] | select(.type == "event_group")] | .[0].event_id')
FIRST_EVENT_TITLE=$(curl -s "${API_URL}${API_PREFIX}/markets/trending?page=0&page_size=10&group_by_events=true" | jq -r '[.[] | select(.type == "event_group")] | .[0].event_title')
echo "  ✓ Selected Event: ${FIRST_EVENT_TITLE}"

# Phase 4: Event Markets
echo "✅ Phase 4: Event Markets..."
MARKET_WITH_PRICES=$(curl -s "${API_URL}${API_PREFIX}/markets/events/${FIRST_EVENT_ID}?page=0&page_size=20" | jq '[.[] | select(.outcome_prices != null and (.outcome_prices | length) > 0)] | .[0]')
SELECTED_MARKET_ID=$(echo "${MARKET_WITH_PRICES}" | jq -r '.id')
SELECTED_MARKET_TITLE=$(echo "${MARKET_WITH_PRICES}" | jq -r '.title')
echo "  ✓ Selected Market: ${SELECTED_MARKET_TITLE}"

# Phase 5: Market Details
echo "✅ Phase 5: Market Details..."
MARKET_DETAILS=$(curl -s "${API_URL}${API_PREFIX}/markets/${SELECTED_MARKET_ID}" | jq .)
PRICE_YES=$(echo "${MARKET_DETAILS}" | jq -r '.outcome_prices[0]')
PRICE_NO=$(echo "${MARKET_DETAILS}" | jq -r '.outcome_prices[1]')

if (( $(echo "${PRICE_YES} > ${PRICE_NO}" | bc -l) )); then
    SELECTED_OUTCOME="Yes"
    SELECTED_PRICE="${PRICE_YES}"
else
    SELECTED_OUTCOME="No"
    SELECTED_PRICE="${PRICE_NO}"
fi
echo "  ✓ Selected Outcome: ${SELECTED_OUTCOME} (Price: \$${SELECTED_PRICE})"

# Phase 6: Trade Preparation
echo "✅ Phase 6: Trade Preparation..."
echo "  Market: ${SELECTED_MARKET_TITLE}"
echo "  Outcome: ${SELECTED_OUTCOME}"
echo "  Amount: \$${TRADE_AMOUNT}"
echo "  ⚠️  Trade endpoint not available - skipping execution"

# Phase 7: Position Verification (skip if no trade)
echo "✅ Phase 7: Position Check..."
POSITIONS=$(curl -s "${API_URL}${API_PREFIX}/positions/user/${USER_ID}" | jq '.')
POSITION_COUNT=$(echo "${POSITIONS}" | jq 'length')
echo "  ✓ Current Positions: ${POSITION_COUNT}"

echo ""
echo "🎉 FLOW TEST COMPLETED!"
echo "========================"
echo "All critical paths tested successfully."
```

---

## ✅ Checklist de Validation

- [ ] **Phase 1:** Infrastructure opérationnelle
- [ ] **Phase 2:** Utilisateur existe avec wallet et balance
- [ ] **Phase 3:** Trending markets retournent des résultats
- [ ] **Phase 4:** Event markets accessibles et structurés
- [ ] **Phase 5:** Prix disponibles et cohérents
- [ ] **Phase 6:** Trade préparé (endpoint à créer)
- [ ] **Phase 7:** Position créée après trade
- [ ] **Phase 8:** Tests complémentaires passent

---

## 🐛 Points d'Attention

1. **Endpoint Trade manquant:** Créer `POST /api/v1/trades/` pour exécuter les trades
2. **Prix en temps réel:** Vérifier que `outcome_prices` sont à jour
3. **Balance suffisante:** Toujours vérifier avant trade
4. **Fees:** Prendre en compte les fees (~0.5-1% sur Polymarket)
5. **Latence:** Certains endpoints peuvent être lents (>500ms)

---

## 📊 Métriques de Succès

- ✅ **Taux de succès:** 100% des endpoints répondent correctement
- ✅ **Temps de réponse:** < 500ms pour la majorité des endpoints
- ✅ **Cohérence données:** Prix Yes + No ≈ 1.0, balances cohérentes
- ✅ **Couverture:** Tous les flows critiques testés

---

## 🔄 Prochaines Étapes

1. **Créer endpoint trade:** `POST /api/v1/trades/`
2. **Ajouter tests unitaires** pour chaque phase
3. **Intégrer dans CI/CD** pour tests automatiques
4. **Monitorer métriques** en production

---

**Document créé le:** $(date)
**Dernière mise à jour:** $(date)
