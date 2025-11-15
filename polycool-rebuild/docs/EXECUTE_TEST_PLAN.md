# 🚀 Guide d'Exécution du Plan de Test Automatisé

Ce guide vous aide à exécuter le plan de test complet pour valider tous les flows critiques de l'API Polycool.

---

## 📋 Prérequis

### 1. Dépendances système

Vérifiez que les outils suivants sont installés :

```bash
# Vérifier jq (JSON processor)
which jq || brew install jq

# Vérifier bc (calculator pour comparaisons float)
which bc || brew install bc

# Vérifier curl (normalement déjà installé)
which curl || echo "curl not found"
```

### 2. Services démarrés

Avant d'exécuter les tests, assurez-vous que tous les services sont démarrés :

```bash
# Option 1: Vérifier les services manuellement
./scripts/dev/test-services.sh

# Option 2: Démarrer tous les services
./scripts/dev/start-all.sh

# Option 3: Démarrer uniquement l'API (si vous testez seulement l'API)
./scripts/dev/start-api.sh
```

**Vérifications attendues :**
- ✅ Redis : `redis-cli ping` → `PONG`
- ✅ API : `curl http://localhost:8000/health/live` → `{"status": "alive"}`
- ✅ Database : connexion Supabase opérationnelle

### 3. Variables d'environnement

Le script utilise ces variables par défaut (vous pouvez les surcharger) :

```bash
export API_URL="http://localhost:8000"
export API_PREFIX="/api/v1"
export USER_ID="6500527972"  # Utilisateur de test avec balance
```

---

## 🎯 Exécution du Test

### Méthode 1 : Exécution directe

```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild

# Exécuter le script complet
./scripts/dev/test-flow-complete.sh
```

### Méthode 2 : Exécution avec variables personnalisées

```bash
# Tester avec un autre utilisateur
USER_ID=1234567890 ./scripts/dev/test-flow-complete.sh

# Tester avec une API distante
API_URL="https://polycool-api-production.up.railway.app" ./scripts/dev/test-flow-complete.sh
```

### Méthode 3 : Exécution phase par phase

Le script exécute automatiquement toutes les phases, mais vous pouvez aussi tester manuellement :

```bash
# Phase 1: Infrastructure
curl -s "http://localhost:8000/health/live" | jq .

# Phase 2: User Info
curl -s "http://localhost:8000/api/v1/users/6500527972" | jq .

# Phase 3: Trending Markets
curl -s "http://localhost:8000/api/v1/markets/trending?page=0&page_size=10&group_by_events=true" | jq .

# ... etc (voir TEST_PLAN_AUTOMATED.md pour toutes les phases)
```

---

## 📊 Phases du Test

Le script exécute automatiquement ces 8 phases :

1. **Phase 1: Vérification Infrastructure** ✅
   - Health check API (`/health/live`)
   - Ready check avec composants (`/health/ready`)
   - Redis connectivity

2. **Phase 2: Informations Utilisateur** 👤
   - Récupération données utilisateur
   - Vérification wallet balance
   - Liste des positions existantes

3. **Phase 3: Découverte Marchés (Trending)** 🔥
   - Récupération trending markets groupés par events
   - Analyse structure des résultats
   - Vérification pagination

4. **Phase 4: Exploration Event** 📦
   - Récupération marchés d'un event
   - Filtrage marchés avec prix disponibles

5. **Phase 5: Détails Marché & Prix** 💰
   - Détails complets du marché
   - Analyse des prix (Yes/No)
   - Sélection outcome le plus cher
   - Vérification liquidité et statut actif

6. **Phase 6: Sélection Outcome & Trade** 🎯
   - Vérification balance suffisante
   - Préparation données de trade
   - Exécution trade (si endpoint disponible)
   - ⚠️ **Note:** L'endpoint `/api/v1/trades/` n'existe pas encore

7. **Phase 7: Vérification Position** 📈
   - Vérification nouvelle position créée
   - Vérification balance mise à jour
   - Détails position

8. **Phase 8: Tests Complémentaires** 🔍
   - Recherche de marchés
   - Marchés par catégorie
   - Fetch marché on-demand
   - Performance (temps de réponse)

---

## ✅ Résultats Attendus

### Succès complet

Si tout fonctionne correctement, vous devriez voir :

```
🧪 POLYCOOL API - FLOW COMPLET TEST
====================================
User ID: 6500527972
Trade Amount: $2.00
API URL: http://localhost:8000

✅ Phase 1: Infrastructure Checks...
✅ API Health Check: OK
✅ API Ready Check: OK

✅ Phase 2: User Information...
✅ User found: ...
✅ Wallet Balances: ...

✅ Phase 3: Trending Markets Discovery...
✅ Found X trending items

... (toutes les phases)

🎉 FLOW TEST COMPLETED!
====================================
All critical paths tested successfully.
```

### Erreurs communes

#### 1. API non démarrée

```
❌ API Health Check: FAILED
```

**Solution :**
```bash
./scripts/dev/start-api.sh
# Attendre 5-10 secondes puis réessayer
```

#### 2. Redis non démarré

```
❌ Redis connection failed
```

**Solution :**
```bash
# Démarrer Redis localement
redis-server

# Ou vérifier si Redis est en cours d'exécution
redis-cli ping
```

#### 3. Utilisateur non trouvé

```
❌ User 6500527972 not found
```

**Solution :**
- Vérifier que l'utilisateur existe en base de données
- Ou utiliser un autre `USER_ID` existant

#### 4. Aucun marché trending

```
❌ No trending markets found
```

**Solution :**
- Vérifier que le poller a bien rempli la base de données
- Vérifier que les marchés sont actifs

#### 5. Endpoint trade manquant

```
⚠️ Trade endpoint not available (POST /api/v1/trades/)
```

**Note :** C'est normal ! L'endpoint de trading n'est pas encore implémenté. Le script continue quand même et teste tout le reste.

---

## 🔍 Debugging

### Mode verbose

Pour voir les réponses complètes de l'API, modifiez temporairement le script :

```bash
# Remplacer les curl -s par curl (sans -s pour voir les headers)
# Ou ajouter | jq . après chaque curl pour voir le JSON complet
```

### Vérifier les logs

```bash
# Logs API
tail -f logs/api.log

# Logs en temps réel
./scripts/dev/view-logs.sh
```

### Tester un endpoint spécifique

```bash
# Tester un endpoint manuellement
curl -v "http://localhost:8000/api/v1/markets/trending?page=0&page_size=5" | jq .

# Avec authentification (si nécessaire)
curl -H "Authorization: Bearer TOKEN" "http://localhost:8000/api/v1/..."
```

---

## 📝 Checklist de Validation

Avant de considérer les tests comme réussis, vérifiez :

- [ ] **Phase 1:** Infrastructure opérationnelle (API, Redis, DB)
- [ ] **Phase 2:** Utilisateur existe avec wallet et balance > $2
- [ ] **Phase 3:** Trending markets retournent des résultats
- [ ] **Phase 4:** Event markets accessibles et structurés
- [ ] **Phase 5:** Prix disponibles et cohérents (Yes + No ≈ 1.0)
- [ ] **Phase 6:** Trade préparé (endpoint à créer)
- [ ] **Phase 7:** Positions accessibles (même si vide)
- [ ] **Phase 8:** Tests complémentaires passent (search, categories)

---

## 🚨 Points d'Attention

1. **Endpoint Trade manquant :**
   - L'endpoint `POST /api/v1/trades/` n'existe pas encore
   - Le script détecte automatiquement et continue sans erreur
   - Pour tester les trades, il faudra créer cet endpoint

2. **Prix en temps réel :**
   - Les prix peuvent être mis en cache (TTL 5 min)
   - Si un marché n'a pas de prix, le script essaie de le fetch on-demand

3. **Balance suffisante :**
   - Le script vérifie que la balance est suffisante avant de préparer le trade
   - Si insuffisante, un warning est affiché mais le test continue

4. **Latence :**
   - Certains endpoints peuvent être lents (>500ms)
   - Le script mesure les performances en Phase 8

---

## 🔄 Prochaines Étapes

Après avoir exécuté les tests avec succès :

1. **Créer endpoint trade :** `POST /api/v1/trades/`
2. **Ajouter tests unitaires** pour chaque phase
3. **Intégrer dans CI/CD** pour tests automatiques
4. **Monitorer métriques** en production

---

## 📚 Ressources

- **Plan de test complet :** `docs/TEST_PLAN_AUTOMATED.md`
- **Script de test :** `scripts/dev/test-flow-complete.sh`
- **Script de vérification services :** `scripts/dev/test-services.sh`
- **Documentation API :** `http://localhost:8000/docs` (Swagger UI)

---

**Dernière mise à jour :** $(date)
