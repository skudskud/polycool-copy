# Problèmes identifiés dans la stratégie d'unsubscription

## 🔴 Problèmes critiques

### 1. **Race condition lors de la vérification des positions actives**

**Problème** :
- La position est fermée dans la DB (`commit()` ligne 483 dans `crud.py`)
- Puis on vérifie les positions actives pour décider d'unsubscribe
- Entre ces deux étapes, une nouvelle position pourrait être créée par un autre utilisateur
- On va quand même unsubscribe alors qu'il y a maintenant une position active

**Impact** :
- Unsubscription prématurée si une nouvelle position est créée juste après la fermeture
- Le market source passe à 'poll' alors qu'il devrait rester 'ws'

**Code concerné** :
```python
# crud.py ligne 483-507
await db.commit()  # Position fermée
# ... plus tard ...
await websocket_manager.unsubscribe_user_from_market(...)  # Vérifie positions actives
```

**Solution recommandée** :
- Vérifier les positions actives AVANT de fermer la position (dans la même transaction)
- Ou utiliser un lock/verrouillage pour éviter les race conditions

---

### 2. **Double vérification redondante et potentiellement conflictuelle**

**Problème** :
- `on_position_closed()` dans `subscription_manager.py` vérifie et met à jour le source (lignes 100-201)
- `_ensure_market_source_updated()` dans `websocket_manager.py` vérifie et met à jour le source aussi (lignes 153-232)
- Ces deux méthodes sont appelées séquentiellement dans `unsubscribe_user_from_market()` (lignes 138 et 142)

**Impact** :
- Appels API/DB redondants
- Risque de conflits si les deux méthodes s'exécutent en parallèle
- Logs confus avec deux vérifications pour la même chose

**Code concerné** :
```python
# websocket_manager.py ligne 138-142
await self.subscription_manager.on_position_closed(user_id, market_id)  # Vérifie + met à jour
await self._ensure_market_source_updated(user_id, market_id)  # Vérifie + met à jour encore
```

**Solution recommandée** :
- Supprimer la double vérification
- Garder seulement `on_position_closed()` qui est plus complète
- Ou faire en sorte que `_ensure_market_source_updated()` ne vérifie que si `on_position_closed()` n'a pas réussi

---

### 3. **Problème de cache avec SKIP_DB=true**

**Problème** :
- Quand on ferme une position, le cache n'est invalidé que dans l'endpoint API (`positions.py` ligne 467)
- Mais `close_position()` dans `crud.py` n'invalide pas le cache directement
- Quand `on_position_closed()` vérifie via API avec `use_cache=False`, le cache est bien invalidé (ligne 421 dans `api_client.py`)
- MAIS : Si l'API a un cache interne ou si la requête passe par un autre chemin, on pourrait avoir des données obsolètes

**Impact** :
- Vérification des positions actives avec des données en cache
- Unsubscription incorrecte si le cache n'est pas à jour

**Code concerné** :
```python
# crud.py : Pas d'invalidation de cache après close_position()
# api_client.py ligne 421 : Invalidation seulement si use_cache=False
```

**Solution recommandée** :
- Invalider le cache explicitement dans `close_position()` avant de vérifier les positions
- S'assurer que tous les chemins invalident le cache correctement

---

### 4. **Pas de transaction atomique pour la mise à jour du source**

**Problème** :
- La fermeture de position est dans une transaction DB (ligne 483)
- Mais la mise à jour du source se fait APRÈS, dans une transaction séparée (ligne 169 dans `subscription_manager.py`)
- Si la mise à jour du source échoue, la position reste fermée mais le source reste 'ws'

**Impact** :
- État incohérent : position fermée mais source='ws'
- Le cleanup périodique devra corriger cela plus tard

**Solution recommandée** :
- Si possible, mettre à jour le source dans la même transaction que la fermeture de position
- Ou avoir un mécanisme de retry pour la mise à jour du source

---

### 5. **Vérification des positions actives avec amount > 0**

**Problème** :
- Quand on ferme une position, on met `amount = 0.0` (ligne 476 dans `crud.py`)
- La vérification filtre avec `amount > 0` (ligne 122 dans `subscription_manager.py`)
- C'est cohérent MAIS : Si une position a `amount = 0` mais `status = 'active'`, elle ne sera pas comptée

**Impact** :
- Positions avec amount=0 et status='active' ne sont pas comptées
- Unsubscription prématurée si toutes les positions ont amount=0

**Code concerné** :
```python
# crud.py ligne 476
position.amount = 0.0  # Set amount to 0 when closing

# subscription_manager.py ligne 122
active_positions = [p for p in positions_list
                  if p.get('status') == 'active'
                  and p.get('amount', 0) > 0]  # Filtre amount > 0
```

**Solution recommandée** :
- S'assurer que toutes les positions fermées ont `status='closed'` ET `amount=0`
- La vérification actuelle est correcte, mais il faut s'assurer de la cohérence

---

### 6. **Cleanup périodique ne met pas à jour le source en mode SKIP_DB=true**

**Problème** :
- Le cleanup périodique (`_cleanup_unused_subscriptions`) désabonne les token_ids (ligne 330)
- Mais il ne met à jour le source que si `SKIP_DB=false` (lignes 347-374)
- En mode `SKIP_DB=true`, le source n'est jamais mis à jour par le cleanup

**Impact** :
- Markets avec source='ws' qui devraient être 'poll' ne sont jamais nettoyés automatiquement
- Il faut exécuter un script manuel pour nettoyer

**Code concerné** :
```python
# subscription_manager.py ligne 337-344
if SKIP_DB:
    # ... pas de mise à jour du source ...
    pass  # API doesn't have a direct way to query markets by source
```

**Solution recommandée** :
- Ajouter une logique pour mettre à jour le source via API dans le cleanup périodique
- Ou créer un endpoint API pour nettoyer les markets avec source='ws' et pas de positions actives

---

## 🟡 Problèmes mineurs

### 7. **Pas de retry en cas d'échec de la mise à jour du source**

**Problème** :
- Si la mise à jour du source échoue (API timeout, erreur réseau), il n'y a pas de retry
- Le fallback `_update_market_source_fallback()` est appelé mais peut aussi échouer

**Impact** :
- État incohérent qui nécessite un cleanup manuel

**Solution recommandée** :
- Ajouter un mécanisme de retry avec backoff exponentiel
- Ou utiliser un job de background pour corriger les états incohérents

---

### 8. **Logs insuffisants pour le debugging**

**Problème** :
- Les erreurs sont loggées mais pas toujours avec assez de contexte
- Difficile de tracer pourquoi un market n'a pas été nettoyé

**Solution recommandée** :
- Ajouter plus de logs avec des IDs de transaction/request
- Logger les états avant/après les opérations critiques

---

## 📋 Recommandations prioritaires

1. **URGENT** : Corriger la race condition (#1)
2. **URGENT** : Supprimer la double vérification (#2)
3. **IMPORTANT** : Améliorer l'invalidation du cache (#3)
4. **IMPORTANT** : Corriger le cleanup périodique en mode SKIP_DB=true (#6)
5. **MOYEN** : Ajouter des transactions atomiques (#4)
6. **MOYEN** : Ajouter un mécanisme de retry (#7)
