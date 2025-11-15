# 🔍 INVESTIGATION: Problèmes de Récupération des Marchés Polymarket

## ⚠️ PROBLÈMES IDENTIFIÉS

### 1. **STATUT ACTIVE ATTRIBUÉ À DES MARCHÉS EXPIRÉS (PRINCIPAL)**
- **Symptôme**: 17,403 marchés marqués comme `ACTIVE` dont beaucoup datent de 2021-2023
- **Cause**: Logique défectueuse dans `poller.py:240-256`
- **Impact**: Les données affichent des marchés anciens comme tradables alors qu'ils sont fermés

#### Exemple de données incohérentes:
```
market_id: "251124" | Basketball 2023-05-22
status: "ACTIVE" (❌ INCORRECT)
end_date: "2023-05-22" (c'était il y a 2+ ans)
accepting_orders: true (❌ INCORRECT)
tradeable: false
created_at: "2023-05-20"

market_id: "240589" | Brésil 2022
status: "ACTIVE" (❌ INCORRECT)
end_date: "2022-10-30"
created_at: "2022-01-11"
accepting_orders: true
```

---

## 🐛 ROOT CAUSES

### Problème #1: Logique de Statut Défectueuse

```python
# ACTUEL (ligne 248-256 dans poller.py):
if is_closed or (end_date and end_date < now):
    status = "CLOSED"
    accepting_orders = False
    tradeable = False
else:
    status = "ACTIVE"  # ❌ Tous les autres cas deviennent ACTIVE!
    accepting_orders = is_active  # ❌ Prend la valeur de l'API
    tradeable = is_active and not is_closed and (not end_date or end_date > now)
```

**Le problème**:
- La logique dit: "Si fermé OU date passée → CLOSED, SINON → ACTIVE"
- Mais l'API Gamma retourne `closed=false` pour les ANCIENS marchés aussi
- Donc les anciens marchés avec `closed=false` deviennent ACTIVE

### Problème #2: `accepting_orders` Incorrect

- Le code assigne `accepting_orders = is_active` (valeur brute de l'API)
- Mais les ANCIENS marchés de 2023 ont `is_active=true` dans l'API
- **Raison**: Polymarket maintient les données historiques pour la consultation

### Problème #3: Parsing des `outcome_prices`

```python
# Ligne 199 dans poller.py:
price = float(prices_list[i]) if i < len(prices_list) else 0.0
```

**Problème observé**:
- Certains marchés ont `outcome_prices: [0, 1]` ou `[1, 0]`
- Ces valeurs ne sont PAS des probabilités, ce sont des placeholders
- Les vrais marchés 2025 ont des prix comme `[0.37, 0.63]` ou `[0.185, 0.815]`

---

## 📊 DONNÉES ACTUELLES

### Statistiques de la base:
| Métrique | Valeur |
|----------|--------|
| Total marchés | 22,216 |
| Marqués ACTIVE | 17,403 (78%) ❌ |
| Marqués CLOSED | 4,813 (22%) |

### Marchés ACTIFS avec end_date PASSÉE:
Exemple de 5 marchés marqués ACTIVE mais déjà fermés:
1. Basketball 2023-05-22 (end_date: NULL) - tradeable: false ✅
2. Trump indicted (end_date: NULL) - tradeable: false ✅
3. French Open 2022 (end_date: NULL) - tradeable: false ✅
4. Tottenham 2022 (end_date: NULL) - tradeable: false ✅
5. F1 2023 (end_date: NULL) - tradeable: false ✅

**OBSERVATION CLÉE**: Beaucoup de marchés anciens ont `end_date = NULL`!

---

## 🔴 PROBLÈME #4: `end_date` MANQUANTE OU NULL

Recherche SQL révèle:
```
Marchés ACTIFS avec end_date NULL: Nombreux (2021-2023)
Marchés 2025 actuels: Tous ont end_date remplie ✅

Les anciens marchés: Manquent souvent la date d'expiration
```

**Cause probable**:
- L'API Gamma API anciennes réponses n'incluent pas `endDate`
- Polymarket a changé le schéma au fil du temps
- Le parsing ne gère pas ce cas

---

## ✅ COMMENT CORRIGER

### FIX #1: Logique de Statut Robuste

```python
# À la ligne 240-256:
# Déterminer le vrai statut basé sur:
# 1. Si explicitement closed → CLOSED
# 2. Si end_date est passé → CLOSED
# 3. Si end_date est NULL → Utiliser le champ "active" de l'API
# 4. Si récent et end_date futur → Utiliser le champ "active"

status = determine_market_status(
    is_closed=is_closed,
    end_date=end_date,
    api_active=is_active,
    created_at=created_at
)
```

### FIX #2: Valider outcome_prices

```python
# Les prix doivent être dans [0, 1] et réalistes
# Si prices = [0, 1] ou [1, 0]: Ce sont des placeholders
def parse_outcome_prices(prices_list):
    prices = [float(p) for p in prices_list]
    # Filtrer les placeholders
    if prices in [[0, 1], [1, 0], [0.0, 1.0], [1.0, 0.0]]:
        return []  # Pas de prix réel
    # Vérifier que la somme ≈ 1.0 (loi des probabilités)
    if len(prices) >= 2 and abs(sum(prices) - 1.0) > 0.01:
        return []  # Invalide
    return prices
```

### FIX #3: Filtrer les Marchés Expirés

```python
# À la ligne 240-256:
now = datetime.now(timezone.utc)

# Si on a end_date ET c'est dans le passé → DEFINITIVELY CLOSED
if end_date and end_date < now:
    status = "CLOSED"
    accepting_orders = False
    tradeable = False
# Si on a end_date ET c'est dans le futur → Faire confiance à "active"
elif end_date and end_date > now:
    status = "ACTIVE" if is_active else "CLOSED"
    accepting_orders = is_active
    tradeable = is_active and not is_closed
# Si NO end_date ET très ancien (> 1 an) → ASSUME CLOSED
elif not end_date and (datetime.now(timezone.utc) - created_at).days > 365:
    status = "CLOSED"
    accepting_orders = False
    tradeable = False
# Sinon → Faire confiance à "active"
else:
    status = "ACTIVE" if is_active else "CLOSED"
    accepting_orders = is_active
    tradeable = is_active
```

### FIX #4: Améliorer le Filtrage à la Récupération

```python
# À la ligne 137:
# Changer le filtre API pour récupérer SEULEMENT les marchés ACTIFS
url = f"{settings.GAMMA_API_URL}?limit={settings.POLL_LIMIT}&offset={offset}&active=true&order=id&ascending=false"
#                                                                                           ^^^^^^^^^^^^
# ATTENTION: active=true filtre les marchés anciens
```

---

## 🎯 IMPACT SUR LES DONNÉES

### Avant corrections:
- ❌ 17,403 marchés ACTIVE (dont beaucoup de 2021-2023)
- ❌ Outcome prices invalides ([0, 1])
- ❌ Volumes incorrects pour anciens marchés
- ❌ Utilisateurs voient des marchés fermés

### Après corrections:
- ✅ Seuls les vrais marchés actifs (2025) sont ACTIVE
- ✅ Outcome prices valides et réalistes
- ✅ Statut correct reflète la réalité Polymarket
- ✅ Interface utilisateur affiche les bonnes données

---

## 📝 ACTION ITEMS

1. **URGENT**: Corriger la logique de statut dans `poller.py:240-256`
2. **IMPORTANT**: Valider outcome_prices (détecter les [0,1] placeholders)
3. **IMPORTANT**: Ajouter logique end_date handling pour marchés NULL
4. **OPTIONAL**: Ajouter filtrage `active=true` à l'API request
5. **CLEANUP**: Re-exécuter le poller pour nettoyer les données existantes
