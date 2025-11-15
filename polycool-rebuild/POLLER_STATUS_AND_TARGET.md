# 🚀 Poller Status & Target Architecture

**Date:** Novembre 2025
**Status:** ⚠️ **PARTIELLEMENT IMPLÉMENTÉ** - Ready pour déploiement

---

## 📊 Statut Actuel

### ✅ **Implémenté et Fonctionnel**
- **Code poller** : `GammaAPIPollerCorrected` dans `data_ingestion/poller/gamma_api.py`
- **Configuration** : `POLLER_ENABLED` ajouté dans settings
- **Intégration** : Poller ajouté dans `telegram_bot/main.py` (lifespan)
- **Logique résolution** : Détection marchés résolus avec 4 conditions strictes
- **Stockage** : `clob_token_ids` stockés correctement (JSON arrays)
- **Migration** : Script de correction des données existantes

### ❌ **NON déployé en Production**
- **Railway** : Poller PAS déployé (services workers n'incluent que streamer/TP-SL/copy-trading)
- **Database** : Données actuelles peuvent être corrompues (triple JSON encoding)
- **Couverture** : Seulement marchés liés à des events (~99% des marchés)

---

## 🎯 Target Architecture - Hybride Optimisée

### **Objectif : 100% Couverture avec Performance Optimale**

#### **1. Double Poller (Services Railway séparés)**

| Service | Rôle | Intervalle | Couverture |
|---------|------|------------|------------|
| **polycool-poller-events** | Top marchés via events | 30s | 500 marchés events les + volumineux |
| **polycool-poller-standalone** | Marchés standalone | 5min | 500 marchés standalone les + volumineux |
| **polycool-poller-resolutions** | Résolutions + marchés courts | 5min | Tous les marchés (détection changements) |

#### **2. On-Demand Fetching**
- **Endpoint** : `POST /api/v1/markets/fetch/{market_id}`
- **Temps de réponse** : ~0.07s (API + DB)
- **UX** : Bouton "Get Prices" pour marchés non-pollés
- **Cache** : Mise à jour automatique après fetch

#### **3. Détection Marchés Courts**
- **Critère** : Duration < 1 heure (ex: Bitcoin up/down 15min)
- **Polling** : Update chaque 5min au lieu de 30s
- **Auto-détection** : Logique basée sur `startDate`/`endDate`

---

## 🔍 Analyse des Lacunes Actuelles

### **❌ Problèmes du Poller Unique**
1. **Marchés standalone** : 100% non couverts (ex: prédictions Bitcoin individuelles)
2. **Marchés courts** : Peuvent expirer entre 2 polls (60s)
3. **Résolutions** : Détection limitée aux marchés actifs uniquement
4. **Scale** : 2000 events max = limite artificielle

### **❌ Problèmes de Données**
1. **Triple JSON encoding** : `clob_token_ids` corrompus en DB
2. **Freshness** : Données obsolètes pour marchés peu actifs
3. **Couverture** : ~1% des marchés Polymarket manquants

### **❌ Problèmes d'Architecture**
1. **Mono-service** : Pas de résilience (crash = arrêt total)
2. **Même IP** : Rate limiting partagé
3. **Debugging** : Logs mélangés

---

## 🏗️ Plan d'Implémentation

### **Phase 1 : Déploiement Basique** (1 jour) ⚡
```bash
# 1. Lancer migration DB
python scripts/dev/fix_clob_token_ids_migration.py

# 2. Activer poller dans workers
export POLLER_ENABLED=true
railway up --service polycool-workers
```

**Résultat** : Couverture 99% (tous marchés events)

### **Phase 2 : Architecture Hybride** (3-4 jours) 🚀

#### **Jour 1 : Services Multi-Pollers**
```bash
# Créer services séparés
railway service create --name polycool-poller-events
railway service create --name polycool-poller-standalone
railway service create --name polycool-poller-resolutions

# Configurer variables d'environnement
railway variables --service polycool-poller-events --set "POLLER_MODE=events"
railway variables --service polycool-poller-standalone --set "POLLER_MODE=standalone"
railway variables --service polycool-poller-resolutions --set "POLLER_MODE=resolutions"
```

#### **Jour 2 : Logique Spécialisée**
```python
class GammaAPIPollerEvents(GammaAPIPollerCorrected):
    async def _fetch_events_batch(self):
        # Top 500 events + leurs marchés
        return await self._fetch_api("/events?limit=500&closed=false&order=volume")

class GammaAPIPollerStandalone(GammaAPIPollerCorrected):
    async def _fetch_events_batch(self):
        # Top 500 marchés standalone
        return await self._fetch_api("/markets?limit=500&order=volume&eventId=null")
```

#### **Jour 3 : On-Demand System**
```python
# API endpoint
@app.post("/api/v1/markets/fetch/{market_id}")
async def fetch_market_on_demand(market_id: str):
    # Fetch API (0.06s) + Upsert DB (0.01s) = 0.07s total
    pass

# Frontend button
const GetPricesButton = ({marketId}) => {
    const [loading, setLoading] = useState(false);

    const fetchPrices = async () => {
        setLoading(true);
        const response = await api.post(`/markets/fetch/${marketId}`);
        setMarket(response.data.market);
        setLoading(false);
    };

    return (
        <button onClick={fetchPrices} disabled={loading}>
            {loading ? '🔄' : '💰'} Get Prices
        </button>
    );
};
```

#### **Jour 4 : Optimisations**
- Cache management
- Search improvements
- Monitoring métriques
- Tests end-to-end

---

## 📈 Métriques Cibles

### **Couverture Marchés**
- **Actuel** : ~1,600 marchés (events uniquement)
- **Target** : ~3,200 marchés (events + standalone)
- **On-demand** : Tous les marchés Polymarket (~10,000+)

### **Freshness Données**
- **Marchés populaires** : < 30s
- **Marchés standalone** : < 5min
- **Marchés courts** : < 5min
- **On-demand** : < 0.1s

### **Performance API**
- **Batch 500 marchés** : < 0.5s ✅
- **Marché individuel** : < 0.1s ✅
- **100 events** : < 0.3s ✅

### **Résilience**
- **IPs séparées** : Rate limiting distribué
- **Services isolés** : Crash indépendant
- **Monitoring** : Métriques par service

---

## 🎯 Avantages de l'Architecture Target

### **✅ Couverture Complète**
- **Events** : Tous les marchés groupés (99% des volumes)
- **Standalone** : Marchés individuels populaires
- **On-demand** : Tous les autres marchés à la demande

### **✅ Performance Optimale**
- **Polling intelligent** : Fréquent pour importants, rare pour secondaires
- **Cache efficace** : Données fresh quand nécessaire
- **UX seamless** : Bouton "Get Prices" quasi-instantané

### **✅ Résilience Maximum**
- **Multi-services** : Pas de SPOF (Single Point of Failure)
- **IPs distribuées** : Rate limiting optimisé
- **Monitoring granulaire** : Debug facile par service

### **✅ Coûts Optimisés**
- **Hébergement** : 3 services Railway (~$15/mois total)
- **API calls** : Intelligent batching + caching
- **Storage** : Données compressées efficacement

---

## 🚦 Status de Risque

### **🟢 Risques Faibles**
- **API Performante** : Tests montrent < 0.5s réponses
- **Code Mature** : Poller déjà testé et fonctionnel
- **DB Stable** : Schema éprouvé

### **🟡 Risques Moyens**
- **Rate Limiting** : 3 services = 3x appels API (gestion prudente)
- **Data Consistency** : Synchronisation entre pollers
- **Migration DB** : Impact sur données existantes

### **🔴 Risques Élevés**
- **Complexité déploiement** : 3 services à gérer
- **Debugging** : Logs distribués
- **Coût** : 3x services Railway

---

## 📋 Checklist Déploiement

### **Prérequis**
- [x] Code poller implémenté
- [x] Settings configurés
- [x] Migration DB prête
- [x] Tests API validés

### **Phase 1 - Déploiement Basique**
- [ ] Lancer migration DB
- [ ] Activer `POLLER_ENABLED=true`
- [ ] Déployer workers avec poller
- [ ] Vérifier logs et métriques

### **Phase 2 - Architecture Avancée**
- [ ] Créer 3 services Railway
- [ ] Implémenter logique spécialisée
- [ ] Développer on-demand fetching
- [ ] Tester UX complète

### **Validation**
- [ ] Couverture marchés : 100% target
- [ ] Performance : < 0.1s on-demand
- [ ] Résilience : Crash indépendant
- [ ] UX : Bouton "Get Prices" fonctionnel

---

## 🎉 Résumé

**Statut actuel** : Poller implémenté mais non déployé (couverture ~1%)
**Target** : Architecture hybride (couverture 100% avec performance optimale)
**Effort estimé** : 4 jours pour implémentation complète
**ROI** : Couverture complète + UX parfaite + résilience maximale

**Le système actuel fonctionne, mais l'architecture target offrira une expérience utilisateur exceptionnelle.** 🚀

---

*Dernière mise à jour : Novembre 2025*
