# 🔔 Système de Notifications Centralisé

## Vue d'ensemble

Le système de notifications centralisé fournit une solution unifiée pour gérer tous les types de notifications dans Polycool, avec un focus particulier sur l'efficacité et la scalabilité.

## Architecture

### Composants Principaux

```
┌─────────────────────────────────────────────────────────────┐
│                    Railway Project                            │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ polycool-api │    │ polycool-bot │    │polycool-     │  │
│  │              │    │              │    │  workers     │  │
│  │ FastAPI      │    │ Telegram Bot │    │ Background   │  │
│  │ ✅ DB Access │    │ ❌ No DB     │    │ ✅ DB Access │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
│         │                   │                   │           │
│         └───────────────────┼───────────────────┘           │
│                             │                               │
│              ┌──────────────▼─────────────────────────────┐ │
│              │         NOTIFICATION SERVICE               │ │
│              │   (Redis Queue + Template Engine)          │ │
│              └──────────────┬─────────────────────────────┘ │
│                             │                               │
│                    ┌─────────▼─────────┐                    │
│                    │   Redis (shared)  │                    │
│                    │  Cache + PubSub   │                    │
│                    └────────────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

### Fichiers Implémentés

- `core/models/notification_models.py` - Modèles de données
- `core/services/notification_service.py` - Service centralisé
- `core/services/notification_templates.py` - Templates de messages
- `workers.py` - Intégration worker pour traitement asynchrone

## Types de Notifications

### TP/SL Trigger (`tpsl_trigger`)
Notifications automatiques quand Take Profit ou Stop Loss se déclenchent.

**Exemple de message :**
```
🎉 TAKE PROFIT HIT!

🏷️ Market: Presidential Election 2024
📍 Position: YES
💰 Execution Price: $0.75
💸 Amount Sold: $50.25

📊 P&L: $12.50 (+8.33%)

📈 Use /positions to view updated portfolio.
```

### Copy Trade Signal (`copy_trade_signal`)
Signaux de copy trading pour les leaders suivis.

### Smart Trade Alert (`smart_trade_alert`)
Alertes des stratégies de trading automatique.

### Position Update (`position_update`)
Mises à jour générales des positions.

### System Alert (`system_alert`)
Alertes système (maintenance, erreurs, etc.).

## Fonctionnalités Clés

### ✅ Efficacité
- **Queue Redis** : Traitement asynchrone, pas de blocage du bot
- **Rate limiting** : Prévention du spam API Telegram
- **Batching** : Regroupement des notifications similaires

### ✅ Fiabilité
- **Retry logic** : Tentatives multiples en cas d'échec
- **Dead letter queue** : Gestion des notifications défaillantes
- **Circuit breaker** : Protection contre les pannes

### ✅ Maintenabilité
- **Templates centralisés** : Messages cohérents
- **Service unique** : Point d'entrée unifié
- **Configuration flexible** : Seuils ajustables

## Configuration Rate Limiting

```python
# Limites par utilisateur
limits = {
    'per_minute': 10,   # 10 notifications/minute
    'per_hour': 50,     # 50 notifications/heure
    'per_day': 200      # 200 notifications/jour
}

# Limites globales
global_limits = {
    'per_second': 5     # 5 notifications/seconde max global
}
```

## Intégration dans le Code

### Envoi d'une notification

```python
from core.services.notification_service import get_notification_service
from core.models.notification_models import Notification, NotificationType, NotificationPriority

# Créer la notification
notification = Notification(
    user_id=telegram_user_id,
    type=NotificationType.TPSL_TRIGGER,
    priority=NotificationPriority.HIGH,
    data={
        'position_id': position.id,
        'trigger_type': 'take_profit',
        'current_price': 0.75,
        'sell_amount': 50.25,
        'market_title': 'Market Name',
        'pnl_amount': 12.50,
        'pnl_percentage': 8.33
    }
)

# Envoyer via le service
service = get_notification_service()
result = await service.queue_notification(notification)
```

### Intégration dans TPSL Monitor

Le TP/SL Monitor utilise maintenant le service centralisé :

```python
# Dans tpsl_monitor.py - remplacement de l'ancienne logique
notification_service = get_notification_service()
notification = Notification(
    user_id=user.telegram_user_id,
    type=NotificationType.TPSL_TRIGGER,
    priority=NotificationPriority.HIGH,
    data={...}
)
await notification_service.queue_notification(notification)
```

## Démarrage et Monitoring

### Démarrage Automatique

Le service de notifications démarre automatiquement avec les workers :

```bash
python workers.py  # Inclut le notification service
```

### Monitoring

```python
# Obtenir les statistiques
stats = await notification_service.get_stats()
print(f"Queue size: {stats['queue_size']}")
print(f"Is processing: {stats['is_processing']}")
```

## Logs et Debugging

### Logs Importants

```
📨 Queued notification {id} (type: tpsl_trigger)
✅ Sent notification {id} to user {user_id}
🚫 Rate limit exceeded for user {user_id}
❌ Failed to send notification: {error}
💀 Max retries exceeded for notification {id}
```

### Commandes de Debug

```bash
# Vérifier la queue Redis
redis-cli LLEN notifications:queue

# Voir les notifications en attente
redis-cli LRANGE notifications:queue 0 -1

# Vérifier les dead letters
redis-cli LLEN notifications:dead_letter
```

## Migration depuis l'Ancien Système

### Avant (TP/SL Monitor)
```python
# Ancienne logique - bloquante et limitée
logger.info(f"📨 TP/SL Notification for user {user_id}: {message}...")
```

### Après (Service Centralisé)
```python
# Nouvelle logique - asynchrone et scalable
notification = Notification(user_id=user_id, type=NotificationType.TPSL_TRIGGER, ...)
await notification_service.queue_notification(notification)
```

## Performance et Scalabilité

### Métriques Attendues

- **Latence** : < 100ms pour mise en queue
- **Throughput** : 100+ notifications/minute
- **Fiabilité** : 99.9% de livraison (avec retry)
- **Rate Limiting** : Respect des limites Telegram API

### Optimisations Futures

1. **Priority Queues** : Files d'attente séparées par priorité
2. **Batch Sending** : Regroupement de notifications similaires
3. **Analytics** : Métriques détaillées de livraison
4. **A/B Testing** : Test de templates alternatifs

## Sécurité

- **Rate Limiting** : Protection contre le spam
- **Input Validation** : Validation stricte des données
- **Error Handling** : Gestion sécurisée des erreurs
- **Audit Logging** : Traçabilité complète

---

## 🚀 Prêt pour Production

Le système est maintenant opérationnel et respecte toutes les contraintes :

- ✅ **Efficace** : Pas de blocage du bot, traitement asynchrone
- ✅ **Arborescence préservée** : Intégration propre dans l'architecture existante
- ✅ **Bande passante optimisée** : Rate limiting et queuing intelligents
- ✅ **Micro-service compatible** : Fonctionne avec SKIP_DB=true pour le bot
