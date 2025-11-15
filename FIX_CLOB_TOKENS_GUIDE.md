# 🔧 Guide de Correction des clob_token_ids Corrompus

## 📋 Marche à Suivre

### 1. **Prérequis**
- Python 3.11+ installé
- `asyncpg` et `httpx` installés (`pip install asyncpg httpx`)
- Accès à la base de données Supabase
- Variable d'environnement `DATABASE_URL` configurée (ou hardcodée dans le script)

### 2. **Exécution du Script**

```bash
cd /Users/ulyssepiediscalzi/Documents/polycool_last2/py-clob-client-with-bots
python fix_active_markets_clob_tokens.py
```

**✨ Mode automatique activé par défaut** : Le script traite automatiquement tous les marchés corrompus en boucle jusqu'à ce qu'il n'y en ait plus !

### 3. **Ce que fait le Script**

✅ **Détecte** les marchés ACTIVE avec clob_token_ids corrompus/vides
✅ **Récupère** les données propres depuis l'API Gamma Polymarket
✅ **Corrige** les données dans Supabase par batchs de 10
✅ **Rate limiting** : 2 requêtes API/seconde max (pas de surcharge)
✅ **Optimisé** : Utilise la longueur des strings pour détecter rapidement (évite de parser les très longues chaînes)

### 4. **Configuration**

Le script est configuré pour :
- **API delay** : 0.5s entre requêtes (max 2 req/sec)
- **Batch size** : 10 marchés par batch DB
- **Max markets** : 100 marchés par exécution
- **Baseline length** : 170 caractères minimum (2 token IDs normaux = ~161 chars + marge)
- **Max length** : 500 caractères (au-delà = corrompu)

### 5. **Résultat Attendu**

Le script traite automatiquement tous les marchés corrompus en cycles :

```
============================================================
🔄 CYCLE 1
============================================================
📊 Found 100 ACTIVE markets to check...
🔍 Found 100 corrupted markets to fix
...
✅ Cycle 1 complete!
   ✅ Fixed this cycle: 100 markets
   📊 Total fixed so far: 100 markets

============================================================
🔄 CYCLE 2
============================================================
📊 Found 100 ACTIVE markets to check...
🔍 Found 50 corrupted markets to fix
...
✅ Cycle 2 complete!
   ✅ Fixed this cycle: 50 markets
   📊 Total fixed so far: 150 markets

============================================================
🔄 CYCLE 3
============================================================
✅ No corrupted markets found! All ACTIVE markets have valid clob_token_ids.

============================================================
🎉 ALL CYCLES COMPLETE!
   ✅ Total fixed: 150 markets
   ❌ Total failed: 0 markets
   🔄 Total cycles: 3
============================================================
```

### 6. **Configuration du Mode Automatique**

**Par défaut** : `AUTO_CONTINUE = True` - Le script traite automatiquement tous les marchés corrompus en boucle.

**Pour traiter seulement 100 marchés à la fois** (mode manuel) :
```python
AUTO_CONTINUE = False  # Traite seulement un cycle de 100 marchés
```

**Pour traiter plus de 100 marchés par cycle** :
```python
MAX_MARKETS_PER_RUN = 200  # ou plus
```

### 7. **Mode Automatique vs Manuel**

**Mode Automatique (recommandé)** :
- ✅ Traite tous les marchés corrompus automatiquement
- ✅ Continue jusqu'à ce qu'il n'y ait plus de marchés corrompus
- ✅ Parfait pour une correction complète en une seule exécution

**Mode Manuel** :
- ✅ Traite seulement 100 marchés par exécution
- ✅ Utile pour tester ou traiter par petits lots
- ✅ Relance le script manuellement pour continuer

### 8. **Optimisations Appliquées**

✅ **Détection rapide par longueur** :
   - Baseline: 170 chars (minimum pour 2 token IDs valides = ~161 chars + marge)
   - Max: 500 chars (au-delà = corrompu)
   - Évite de parser les très longues chaînes corrompues

✅ **Rate limiting API** :
   - 0.5s entre requêtes
   - Gestion du rate limit (429) avec attente

✅ **Batch updates DB** :
   - 10 marchés par batch
   - 1s de délai entre batchs
   - Transactions pour garantir l'intégrité

### 8. **Vérification Post-Correction**

Pour vérifier qu'un marché spécifique a été corrigé :

```sql
SELECT market_id, title,
       length(clob_token_ids::text) as clob_length,
       clob_token_ids
FROM subsquid_markets_poll
WHERE market_id = '667441';
```

Un clob_token_ids valide devrait avoir :
- Longueur entre 170 et 500 caractères (normalement ~161 chars pour 2 tokens)
- Format JSON valide : `["token_id_1", "token_id_2"]`
- Pas de backslashes multiples (`\\\\`)

### 9. **Maintenance Continue**

**Avec le mode automatique** : Lance le script une seule fois, il traite tous les marchés corrompus automatiquement !

```bash
# Une seule exécution traite TOUS les marchés corrompus
python fix_active_markets_clob_tokens.py
```

Le script s'arrête automatiquement quand il n'y a plus de marchés corrompus.

**Pour une maintenance régulière** : Exécute le script périodiquement (tous les jours ou après chaque cycle de poller) pour corriger les nouveaux marchés corrompus.

### 10. **Troubleshooting**

**Problème** : Script bloque sur la connexion DB
- **Solution** : Vérifie que `DATABASE_URL` est correcte
- **Solution** : Vérifie la connexion réseau à Supabase

**Problème** : Rate limit API (429)
- **Solution** : Le script gère automatiquement avec attente de 5s

**Problème** : Trop de marchés corrompus
- **Solution** : Augmente `MAX_MARKETS_PER_RUN` ou exécute plusieurs fois

---

## 🎯 Résumé

**Script optimisé** qui corrige les clob_token_ids corrompus pour les marchés ACTIVE :
- ✅ **Mode automatique** : Traite tous les marchés corrompus en une seule exécution
- ✅ **Détection rapide par longueur** : Baseline 170 chars (évite parsing long)
- ✅ **Rate limiting API** : 2 req/sec max (pas de surcharge)
- ✅ **Batch updates DB** : 10 marchés par batch (efficace)
- ✅ **100 marchés par cycle** : ~2-3 minutes par cycle
- ✅ **Continue automatiquement** : Jusqu'à ce qu'il n'y ait plus de marchés corrompus

**Une seule exécution = Tous les marchés corrompus corrigés !** 🚀

**Le système de prévention dans le poller empêche les nouvelles corruptions !** 🛡️
