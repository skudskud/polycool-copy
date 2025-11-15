# Unified Backfill System

## Overview
Le système de backfill unifié garantit une couverture complète des marchés avec **ZERO ORPHELINS**.

## Architecture
- **`UnifiedBackfillPoller`**: Backfill one-shot complet avec stratégie anti-orphelins
- **4 phases**:
  1. Récupération complète via `/events` → `/events/{id}`
  2. Récupération marchés standalone via `/markets`
  3. **Vérification orphelins** avec enrichissement automatique
  4. Enrichissement tags + upsert final

## Scripts Disponibles

### 1. Lancement du Backfill
```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
python3 scripts/run_unified_backfill.py
```

### 2. Validation Post-Backfill
```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
python3 scripts/validate_backfill.py
```

## Stratégie Anti-Orphelins

### Phase 1: Récupération Complète des Événements
- `/events` pour lister tous les événements actifs
- `/events/{id}` pour chaque événement → **métadonnées complètes + dates**
- Extraction de tous les marchés avec `event_title` garanti

### Phase 2: Marchés Standalone
- `/markets` pour récupérer les marchés hors événements
- Filtrage des doublons déjà trouvés
- Extraction des métadonnées d'événements si présentes

### Phase 3: Vérification d'Orphelins (CRITIQUE)
- **Détection**: marchés avec `event_id` mais sans `event_title`
- **Enrichissement**: appels `/events/{id}` pour récupérer les métadonnées manquantes
- **Garantie**: zero marchés orphelins à la fin

### Phase 4: Finalisation
- Enrichissement avec tags pour catégorisation
- Upsert par batches avec rate limiting

## Métriques de Succès

### ✅ Parfait
- 0 marchés orphelins
- 1000+ marchés au total
- Répartition équilibrée event/standalone
- Métadonnées complètes (dates, catégories, etc.)

### ⚠️ Acceptable
- < 5 orphelins non enrichissables
- Données cohérentes dans l'ensemble

### ❌ Échec
- > 10 orphelins
- Pas de marchés event
- Erreurs de métadonnées généralisées

## Debugging

Si des orphelins persistent :
1. Vérifier la connectivité API `/events/{id}`
2. Vérifier les event_ids dans les données
3. Logs détaillés dans les appels d'enrichissement

## Performance
- **Durée estimée**: 30-60 minutes pour ~2000 marchés
- **Rate limiting**: 3-5 req/s max
- **Batches**: 50 marchés par upsert, 200 events par fetch

## Prochaines Étapes
Après validation réussie :
- Implémenter les passes de maintenance (prix frais, résolutions)
- Activer le système de production
