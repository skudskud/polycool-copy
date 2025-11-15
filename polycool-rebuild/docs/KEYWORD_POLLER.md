# 🔍 Keyword Poller - Poller Spécialisé pour Markets avec Keywords

## 📋 Description

Le `KeywordPoller` est un poller spécialisé qui combine **découverte**, **mise à jour** et **vérification de résolution** pour les markets contenant des keywords spécifiques.

## 🎯 Fonctionnalités

### 1. Découverte de Nouveaux Markets
- Scanne les top 2000 markets par volume
- Filtre ceux qui contiennent les keywords
- Upsert uniquement les nouveaux (pas déjà en DB)

### 2. Mise à Jour des Markets Existants
- Trouve tous les markets existants avec keywords (via SQL)
- Met à jour jusqu'à 200 markets par cycle
- Récupère les données fraîches via `/markets/{id}`

### 3. Vérification des Résolutions
- Vérifie les markets expirés ou sans `end_date`
- Détecte les résolutions avec la logique améliorée
- Met à jour le statut de résolution

## 🔑 Keywords Supportés

### Keywords Simples (case-insensitive)
- `bitcoin` - Matches "Bitcoin", "bitcoin", etc.
- `eth` - Matches "Ethereum", "ETH", "eth", etc.
- `solana` - Matches "Solana", "SOL", etc.
- `trump` - Matches "Trump", "trump", etc.
- `elon` - Matches "Elon", "elon", "Elon Musk", etc.
- `israel` - Matches "Israel", "israel", "Israeli", etc.
- `ukraine` - Matches "Ukraine", "ukraine", "Ukrainian", etc.
- `ai` - Matches "AI", "ai", "Artificial Intelligence", etc.

### Pattern Spécial: "what + say"
- Détecte les markets avec "what" ET "say" dans le même texte
- Vérifie que les deux mots sont à moins de 50 caractères l'un de l'autre
- Exemples:
  - ✅ "What will Trump say about..."
  - ✅ "What did Elon say..."
  - ❌ "What happened? They say..." (trop loin)

## ⚙️ Configuration

### Intervalle par Défaut
- **5 minutes** (300 secondes)
- Peut être modifié dans le constructeur

### Limites par Cycle
- **Découverte**: Top 2000 markets scannés
- **Mise à jour**: 200 markets existants max
- **Résolutions**: 100 candidats max

## 📊 Logs

Le poller log:
- Nombre de nouveaux markets découverts
- Nombre de markets mis à jour
- Nombre de markets résolus
- Exemples de markets découverts (debug)

## 🚀 Utilisation

```python
from data_ingestion.poller.keyword_poller import KeywordPoller

# Créer le poller avec intervalle par défaut (5min)
poller = KeywordPoller()

# Ou avec intervalle personnalisé
poller = KeywordPoller(interval=600)  # 10 minutes

# Démarrer le polling
await poller.start_polling()
```

## 🔍 Exemples de Markets Détectés

### Bitcoin
- "Will Bitcoin reach $100k in 2025?"
- "Bitcoin price prediction"
- "Bitcoin ETF approval"

### Ethereum
- "Ethereum 2.0 launch"
- "ETH price above $3000"
- "Ethereum upgrade"

### Trump
- "Will Trump win 2024?"
- "Trump indictment"
- "What will Trump say about..."

### AI
- "AI regulation in 2025"
- "ChatGPT user growth"
- "AI job displacement"

### Pattern "what + say"
- "What will the Fed say about rates?"
- "What did Biden say about Ukraine?"
- "What will Elon say about Twitter?"

## 📈 Performance

- **Fréquence**: 5 minutes
- **API Calls par cycle**: ~300-500 (découverte + mise à jour + résolutions)
- **Rate limiting**: 100-200ms entre chaque appel
- **Durée estimée**: 30-60 secondes par cycle

## ⚠️ Notes Importantes

1. **SQL Injection**: Les keywords sont hardcodés, donc pas de risque d'injection SQL
2. **Double Validation**: SQL pour efficacité, Python pour précision (notamment "what + say")
3. **Allow Resolved**: Le poller utilise `allow_resolved=True` pour mettre à jour les résolutions
4. **Priorité**: Ce poller a une priorité élevée (5min) car les markets avec keywords sont souvent populaires

## 🔧 Personnalisation

Pour ajouter/modifier des keywords:

```python
class CustomKeywordPoller(KeywordPoller):
    KEYWORDS = [
        'bitcoin',
        'eth',
        'solana',
        'trump',
        'elon',
        'israel',
        'ukraine',
        'ai',
        'your_new_keyword',  # Ajouter ici
    ]
```

## 📊 Métriques à Surveiller

```sql
-- Nombre de markets avec keywords
SELECT COUNT(*)
FROM markets
WHERE (
    title ILIKE '%bitcoin%' OR title ILIKE '%eth%' OR title ILIKE '%solana%'
    OR title ILIKE '%trump%' OR title ILIKE '%elon%' OR title ILIKE '%israel%'
    OR title ILIKE '%ukraine%' OR title ILIKE '%ai%'
    OR (title ILIKE '%what%' AND title ILIKE '%say%')
)
AND is_resolved = false;

-- Markets avec keywords résolus récemment
SELECT id, title, resolved_at
FROM markets
WHERE (
    title ILIKE '%bitcoin%' OR title ILIKE '%trump%' OR title ILIKE '%elon%'
)
AND is_resolved = true
ORDER BY resolved_at DESC
LIMIT 10;
```
