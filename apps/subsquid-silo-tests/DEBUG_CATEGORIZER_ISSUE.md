# 🔥 PROBLÈME: Le Categorizer Bloque PASS 2

## Ce que vos logs montrent:

```
15:29:08 - ✅ Poller service starting...
15:29:10 - 🤖 AI categorized market 540206 → Sports  (1 seconde)
15:29:11 - 🤖 AI categorized market 540207 → Sports  (1 seconde)
15:29:12 - 🤖 AI categorized market 540208 → Sports  (1 seconde)
...
15:29:47 - 🤖 AI categorized market 559667 → Geopolitics  (37 secondes pour ~40 markets)
15:31:08 - ✅ Upserted 500 enriched markets  (1 min 21 sec après démarrage)
15:32:18 - ✅ Upserted 500 enriched markets  (70 secondes plus tard)
```

## Analyse Temporelle:

1. **15:29:08 → 15:29:47** (39 sec): AI Categorization de ~40 markets
2. **15:29:47 → 15:31:08** (81 sec): Upsert des 500 premiers markets
3. **Total PASS 1**: ~120 secondes (2 minutes)

**MAIS POLL_MS = 60000 (60 secondes)**

## Le Problème:

### Scenario:

```
Cycle 1 démarre à 15:29:08
├─ PASS 1: Fetch events (15:29:08)
├─ AI categorization (15:29:10 → 15:29:47 = 39 sec)
├─ Enrich tokens (15:29:47 → 15:31:08 = 81 sec)
├─ Upsert chunk 1 (15:31:08)
├─ Upsert chunk 2 (15:32:18)
└─ PASS 2 devrait commencer ICI... MAIS:

Cycle 2 démarre à 15:30:08 (60 sec après Cycle 1)
├─ Nouveau cycle qui INTERROMPT/BLOQUE le Cycle 1
└─ PASS 2 du Cycle 1 NE S'EXÉCUTE JAMAIS!
```

## Code du Categorizer:

```python
# Ligne 1498 dans poller.py
ai_category = await self.categorizer.categorize_market(question, raw_category)
```

```python
# market_categorizer.py ligne 90
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[...],
    temperature=0.0,
    max_tokens=20
)
```

**Chaque appel OpenAI prend ~1 seconde.**

### Limite actuelle:

```python
self.max_categorizations_per_cycle = 50  # Limite à 50 catégorisations
```

- 50 catégorisations × 1 seconde = **50 secondes JUSTE pour l'AI**
- + Fetch events: ~10 secondes
- + Enrich tokens: ~30 secondes
- + Upsert: ~40 secondes
- **TOTAL PASS 1: ~130 secondes**

Mais le cycle redémarre toutes les 60 secondes → **PASS 2 ne s'exécute JAMAIS!**

## 🎯 SOLUTIONS

### Solution 1: DÉSACTIVER l'AI Categorizer (IMMÉDIAT)

**Dans Railway Variables:**
```
OPENAI_API_KEY=   (laisser vide ou supprimer)
```

Cela désactivera le categorizer et PASS 1 devrait terminer en ~30 secondes.

**Vous verrez immédiatement TIER 0 apparaître!**

---

### Solution 2: Réduire max_categorizations_per_cycle à 10

**Modifier ligne 45 dans `poller.py`:**
```python
self.max_categorizations_per_cycle = 10  # ← Réduire de 50 à 10
```

- 10 catégorisations × 1 sec = 10 secondes au lieu de 50
- PASS 1 total: ~50 secondes → assez pour PASS 2

---

### Solution 3: Catégoriser en BACKGROUND (après PASS 2)

**Déplacer la catégorisation APRÈS PASS 2:**

```python
async def poll_cycle(self):
    try:
        # PASS 1: Fetch events (SANS catégorisation)
        events_markets = await self._fetch_and_parse_events()

        # PASS 2: TIER 0 + markets existants
        standalone_markets = await self._fetch_and_update_existing_markets(...)

        # PASS 3: Lifecycle management
        closed_updated = await self._update_closed_markets()

        # PASS 4: PROPOSED → RESOLVED
        proposed_upgraded = await self._upgrade_proposed_to_resolved()

        # ✅ MAINTENANT: Catégoriser en arrière-plan (optionnel)
        if events_markets:
            await self._categorize_markets_background(events_markets)
```

---

### Solution 4: Catégoriser ASYNC en parallèle

**Utiliser asyncio.gather() pour catégoriser plusieurs markets simultanément:**

```python
# Au lieu de:
for market in markets[:50]:
    category = await self.categorizer.categorize_market(...)  # 1 par 1

# Faire:
tasks = [self.categorizer.categorize_market(...) for market in markets[:50]]
categories = await asyncio.gather(*tasks, return_exceptions=True)  # En parallèle
```

Cela réduirait le temps de 50 secondes à ~5 secondes (10x plus rapide).

---

## 🧪 TEST IMMÉDIAT

**Désactivez temporairement le categorizer pour confirmer le diagnostic:**

```bash
# Dans Railway Variables
OPENAI_API_KEY=

# Redéployez et vérifiez les logs
# Vous DEVRIEZ voir:
🚨🚨🚨 [PASS 2 DEBUG] Starting PASS 2...
🚨🚨🚨 [TIER 0 DEBUG] get_user_position_market_ids() returned 44 markets...
```

---

## 📊 Metrics Attendus (SANS categorizer):

```
15:29:08 - ✅ Poller service starting...
15:29:10 - 📊 [PASS 1] Fetching from /events  (2 sec)
15:29:15 - ✅ Upserted 500 markets (PASS 1)   (5 sec)
15:29:20 - ✅ Upserted 500 markets (PASS 1)   (5 sec)
15:29:25 - 🚨🚨🚨 [PASS 2 DEBUG] Starting PASS 2  (25 sec total PASS 1)
15:29:26 - 🚨🚨🚨 [TIER 0 DEBUG] get_user_position_market_ids() returned 44 markets
15:29:30 - ✅ [CYCLE #1] Total upserted: 1200 in 22.5s
```

**Cycle complet: ~30 secondes → PASS 2 s'exécute!**

---

## ✅ Recommandation

1. **IMMÉDIAT**: Désactivez OPENAI_API_KEY dans Railway
2. **Vérifiez**: Les logs doivent montrer TIER 0
3. **Puis**: Ré-activez avec max_categorizations_per_cycle = 5

Cela vous permettra de confirmer que TIER 0 fonctionne, puis de rajouter la catégorisation progressivement.
