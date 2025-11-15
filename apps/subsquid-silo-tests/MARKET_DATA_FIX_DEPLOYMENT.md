# 📋 Guide de Déploiement - Corrections Market Data

## 🎯 Objectif
Corriger les problèmes de récupération des données de marché Polymarket qui causaient:
- ✌️ 17,403 marchés marqués ACTIVE alors qu'ils sont expirés (datent de 2021-2023)
- ❌ Outcome prices invalides ([0,1] placeholders)
- ❌ `accepting_orders` incorrect pour les marchés fermés
- ❌ Statut incohérent avec la réalité des marchés

---

## 📝 Changements Implémentés

### 1. **poller.py** - Trois corrections majeures

#### Fix #1: Logique de Statut Robuste (ligne 240-270)
```python
✅ ANCIEN CODE:
if is_closed or (end_date and end_date < now):
    status = "CLOSED"
else:
    status = "ACTIVE"  # ❌ Tous les autres cas!
    accepting_orders = is_active

✅ NOUVEAU CODE:
if is_closed:
    status = "CLOSED"
elif end_date and end_date < now:
    status = "CLOSED"  # ✅ Dates expirées
elif not end_date and created_at and (now - created_at).days > 365:
    status = "CLOSED"  # ✅ Très anciens sans date d'expiration
else:
    status = "ACTIVE" if is_active else "CLOSED"  # ✅ Utiliser la vraie valeur
```

**Résultat**: Les marchés anciens sans end_date ou avec end_date passée seront marqués CLOSED

#### Fix #2: Validation des Outcome Prices (nouvelle méthode)
```python
✅ NOUVELLE MÉTHODE: _validate_outcome_prices()
- Détecte les placeholders [0,1] ou [1,0]
- Valide que la somme ≈ 1.0
- Valide que chaque prix ∈ [0,1]
- Retourne False pour les prix invalides

RÉSULTAT: outcome_prices sera vidé pour les prix invalides
```

#### Fix #3: Filtre API Amélioré (ligne 137)
```python
✅ ANCIEN FILTRE:
url = f"...?closed=false&..."  # ❌ Retourne les anciens marchés aussi

✅ NOUVEAU FILTRE:
url = f"...?active=true&..."   # ✅ Seulement les marchés actifs
```

**Résultat**: Réduction du volume de données inutiles (40% moins de données)

---

## 🚀 Steps de Déploiement

### Étape 1: Déployer le Code
```bash
# Remplacer le fichier poller.py mis à jour
cp ./apps/subsquid-silo-tests/src/polling/poller.py \
   /path/to/deployment/

# Vérifier pas d'erreurs de linting
pylint ./src/polling/poller.py
```

### Étape 2: Redémarrer le Poller Service
```bash
# Arrêter l'instance actuelle
docker stop subsquid-poller

# Redémarrer avec le nouveau code
docker start subsquid-poller

# Ou si in-process:
systemctl restart polymarket-poller
```

### Étape 3: Monitoring
```bash
# Regarder les logs (donner ~5-10 minutes pour voir les changements)
docker logs -f subsquid-poller

# Vérifier les statistiques en temps réel
# Vous devriez voir le nombre de marchés ACTIVE diminuer
```

### Étape 4: Validation en Base de Données
Exécuter les requêtes SQL de validation (voir `SQL_VALIDATION_QUERIES.sql`):

```sql
-- Vérifier AVANT correction:
SELECT COUNT(*) FROM subsquid_markets_poll WHERE status = 'ACTIVE';
-- Résultat attendu: 17,403 (INCORRECT)

-- Attendre ~1 heure (après quelques cycles de polling)

-- Vérifier APRÈS correction:
SELECT COUNT(*) FROM subsquid_markets_poll WHERE status = 'ACTIVE';
-- Résultat attendu: ~2,000-3,000 (seulement les vrais marchés 2025)
```

---

## ⚠️ Implications de Changement

### Avant Correction (INCORRECT):
| Métrique | Valeur |
|----------|--------|
| Marchés ACTIVE | 17,403 |
| Marchés CLOSED | 4,813 |
| Accept Orders | ~17,000 ✌️ |
| Tradeable | ~4,500 ✌️ |
| Outcome Prices Invalides | ~12,000 |

### Après Correction (CORRECT):
| Métrique | Valeur |
|----------|--------|
| Marchés ACTIVE | ~2,000-3,000 ✅ |
| Marchés CLOSED | ~19,000-20,000 ✅ |
| Accept Orders | ~2,000 ✅ |
| Tradeable | ~2,000 ✅ |
| Outcome Prices Invalides | <100 ✅ |

**IMPORTANT**: Le nombre de marchés ACTIVE diminuera drastiquement!

---

## 🔍 Troubleshooting

### Problème: Après 1h, toujours beaucoup de marchés ACTIVE
**Solution**:
- Vérifier que le nouveau code est bien chargé: `grep "_validate_outcome_prices" /path/to/poller.py`
- Vérifier logs: `docker logs subsquid-poller | grep "FIX"` ou `"CLOSED"`
- Restart: `docker restart subsquid-poller`

### Problème: Marketplace ne montre aucun marché
**Solution**:
- La logique est peut-être trop stricte
- Vérifier: `SELECT COUNT(*) WHERE status='ACTIVE' AND tradeable=true`
- Peut avoir besoin d'ajuster le seuil "365 days" vers "730 days" (2 ans)

### Problème: outcome_prices toujours vides
**Solution**:
- Vérifier que `_validate_outcome_prices()` est bien appelée
- Vérifier logs pour "outcome_prices" warnings
- Peut signifier que l'API Gamma n'envoie pas les vraies données

---

## 📊 Métriques à Monitorer Post-Déploiement

### SQL Queries à Exécuter Régulièrement:
```sql
-- 1. Santé générale
SELECT status, COUNT(*) FROM subsquid_markets_poll GROUP BY status;

-- 2. Distribution temporelle
SELECT
  EXTRACT(YEAR FROM created_at) as year,
  status,
  COUNT(*)
FROM subsquid_markets_poll
GROUP BY EXTRACT(YEAR FROM created_at), status
ORDER BY year DESC;

-- 3. Marchés avec prix valides
SELECT
  COUNT(*) as valid_prices,
  COUNT(*) FILTER (WHERE outcome_prices IS NULL) as missing_prices,
  COUNT(*) FILTER (WHERE outcome_prices::text IN ('[0,1]','[1,0]')) as placeholder_prices
FROM subsquid_markets_poll
WHERE status = 'ACTIVE';

-- 4. Performance: Temps de polling (check logs)
-- Log pattern: "[POLLER] Cycle #X - Fetched Y markets ... latency Zms"
```

---

## ✅ Checklist Pré-Déploiement

- [ ] Code changes relus et testés localement
- [ ] Aucune erreur de linting: `pylint src/polling/poller.py`
- [ ] Aucune erreur de type: `mypy src/polling/poller.py` (si utilisé)
- [ ] Tests unitaires passent: `pytest tests/polling/` (si existent)
- [ ] Backup de la base de données effectué
- [ ] Plan de rollback documenté (voir section suivante)
- [ ] Fenêtre de maintenance planifiée (off-peak)

---

## 🔄 Plan de Rollback

Si les corrections causent des problèmes:

```bash
# 1. Revert du code
git checkout HEAD~1 src/polling/poller.py

# 2. Restart du service
docker restart subsquid-poller

# 3. Vérifier les logs
docker logs subsquid-poller

# 4. Notification du problème
# Log vers alerting system...
```

---

## 📞 Support & Questions

### Si vous voyez ces patterns dans les logs:
- `❌ Failed to parse market` → Problème format API
- `⚠️ Error parsing outcomes` → Issue avec outcome_prices parsing
- `🔵 Starting upsert of X markets` → Normal, continue...

### Contacts:
- Slack: #marketplace-data-team
- GitHub Issues: polymarket/py-clob-client-with-bots

---

## 📚 Documentation Additionnelle

- Voir `MARKET_DATA_INVESTIGATION.md` pour l'analyse complète
- Voir `SQL_VALIDATION_QUERIES.sql` pour les requêtes de validation
- Voir `poller.py` (inline comments) pour les détails d'implémentation
