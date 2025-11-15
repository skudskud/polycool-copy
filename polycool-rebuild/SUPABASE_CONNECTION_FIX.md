# 🔧 CORRECTIONS CONNEXIONS SUPABASE - Timeout Fixes

**Date:** 2025-01-XX
**Problème:** Timeouts de connexion Supabase lors de pics de webhooks

---

## 🚨 PROBLÈME IDENTIFIÉ

### Symptômes
- Erreurs `connection timeout expired` après plusieurs webhooks simultanés
- L'API fonctionne bien au début, puis échoue avec des timeouts
- Erreurs psycopg: `Multiple connection attempts failed`

### Causes Racines
1. **Timeout trop court:** 10 secondes insuffisant pour Supabase Pooler
2. **Pas de gestion d'erreurs:** Le webhook handler principal ne gérait pas les timeouts
3. **Erreurs non retryables:** `connection timeout expired` n'était pas dans la liste des erreurs retryables

---

## ✅ CORRECTIONS APPLIQUÉES

### 1. **Augmentation du Timeout de Connexion**

**Fichier:** `core/database/connection.py`

**Avant:**
```python
engine_kwargs["connect_args"] = {
    "connect_timeout": 10,  # 10 second connection timeout
}
```

**Après:**
```python
# Check if this is Supabase Pooler (needs longer timeout)
is_supabase_pooler = "pooler.supabase.com" in database_url
connect_timeout = 30 if is_supabase_pooler else 10  # 30s for Supabase, 10s for others

engine_kwargs["connect_args"] = {
    "connect_timeout": connect_timeout,  # Increased timeout for Supabase Pooler
}
```

**Impact:** Timeout augmenté de 10s → 30s pour Supabase Pooler

---

### 2. **Gestion d'Erreurs dans le Webhook Handler Principal**

**Fichier:** `telegram_bot/api/v1/webhooks/copy_trade.py`

**Avant:**
```python
# Get watched address record
async with get_db() as db:
    result = await db.execute(...)
    watched_address = result.scalar_one_or_none()
```

**Après:**
```python
# Get watched address record (with timeout handling)
watched_address = None
try:
    async with get_db() as db:
        result = await db.execute(...)
        watched_address = result.scalar_one_or_none()
except Exception as db_error:
    error_msg = str(db_error).lower()
    # Check if this is a connection timeout/error
    if any(keyword in error_msg for keyword in [
        'connection timeout',
        'connection timed out',
        'could not connect to server',
        'server closed the connection'
    ]):
        logger.error(f"❌ DB connection error in webhook handler: {db_error}")
        # Return 200 OK to prevent retry from indexer, but log error
        return WebhookResponse(
            status="error",
            message="Database temporarily unavailable"
        )
    else:
        # Re-raise other errors
        raise
```

**Impact:** Le webhook handler gère maintenant les timeouts gracieusement au lieu de crasher

---

### 3. **Ajout d'Erreurs Retryables**

**Fichier:** `telegram_bot/api/v1/webhooks/copy_trade.py`

**Avant:**
```python
if any(keyword in error_msg for keyword in [
    'tenant or user not found',
    'connection pool exhausted',
    'connection timed out',
    'server closed the connection unexpectedly',
    'could not connect to server'
]):
```

**Après:**
```python
if any(keyword in error_msg for keyword in [
    'tenant or user not found',
    'connection pool exhausted',
    'connection timeout',
    'connection timed out',
    'server closed the connection unexpectedly',
    'could not connect to server',
    'connection timeout expired'  # Added for psycopg errors
]):
```

**Impact:** Les erreurs `connection timeout expired` sont maintenant retryables avec backoff exponentiel

---

## 📊 ARCHITECTURE DE CONNEXION

### Configuration Actuelle

```
┌─────────────────┐
│  FastAPI API    │
│  (api_only.py)  │
└────────┬────────┘
         │
         │ NullPool (nouvelle connexion par requête)
         │ connect_timeout: 30s (Supabase)
         │
         ▼
┌─────────────────┐
│ Supabase Pooler │
│  (port 5432)    │
│  Limit: ~30-40  │
│  connections    │
└─────────────────┘
```

### Gestion des Webhooks

```
Webhook Request
    │
    ├─► Fast check: Cache (watched addresses)
    │
    ├─► DB Query: Get WatchedAddress
    │   └─► Try/Catch timeout errors
    │       └─► Return 200 OK if timeout (prevent retry)
    │
    ├─► Background Task: Store Trade (with retry)
    │   └─► Retry 3x with exponential backoff
    │       └─► Log error if all retries fail
    │
    └─► Background Task: Publish to Redis
        └─► Non-blocking
```

---

## 🎯 RÉSULTATS ATTENDUS

### Avant les Corrections
- ❌ Webhooks crashaient avec `connection timeout expired`
- ❌ Pas de retry pour les erreurs de timeout
- ❌ Timeout trop court (10s) pour Supabase

### Après les Corrections
- ✅ Timeout augmenté à 30s pour Supabase Pooler
- ✅ Gestion gracieuse des timeouts dans le webhook handler
- ✅ Retry automatique avec backoff exponentiel
- ✅ Webhooks retournent 200 OK même en cas de timeout DB (évite retry indexer)

---

## 🔍 MONITORING

### Logs à Surveiller

**Succès:**
```
✅ [WEBHOOK] Processed BUY trade for 0x...
✅ Stored trade ... in DB
```

**Erreurs Temporaires (Retry):**
```
⚠️ DB connection error (attempt 1/3): connection timeout expired
⚠️ DB connection error (attempt 2/3): connection timeout expired
✅ Stored trade ... in DB  # Success after retry
```

**Erreurs Critiques:**
```
❌ DB connection error in webhook handler: connection timeout expired
❌ DB connection failed after 3 attempts: connection timeout expired
```

---

## 📝 NOTES IMPORTANTES

### Pourquoi NullPool?

Le code utilise `NullPool` (pas de pool de connexions) car:
- PgBouncer transaction pooling ne supporte pas les prepared statements
- NullPool évite les conflits de prepared statements
- Chaque requête crée une nouvelle connexion

### Limitations Supabase Pooler

- **Limite:** ~30-40 connexions simultanées
- **Timeout:** Connexions idle fermées après ~5 minutes
- **Recommandation:** Utiliser le pooler en mode transaction (port 6543) si possible

### Alternatives Futures

Si les problèmes persistent:
1. **Utiliser un pool limité** au lieu de NullPool (avec gestion des prepared statements)
2. **Augmenter le timeout** à 60s si nécessaire
3. **Implémenter un circuit breaker** pour éviter de spammer Supabase quand il est down
4. **Utiliser le port 6543** (transaction pooling) au lieu de 5432 (session pooling)

---

## ✅ CHECKLIST DE VALIDATION

- [x] Timeout augmenté à 30s pour Supabase
- [x] Gestion d'erreurs dans webhook handler principal
- [x] Erreurs `connection timeout expired` ajoutées aux retryables
- [ ] Tests avec pics de webhooks simultanés
- [ ] Monitoring des erreurs de connexion
- [ ] Documentation mise à jour

---

**Status:** ✅ Corrections appliquées
**Prochaine étape:** Déployer et monitorer les logs
