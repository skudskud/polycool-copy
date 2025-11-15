# 🔧 Fix: Telegram User ID Integer Overflow

## Problème identifié

**Erreur:** `(psycopg.errors.NumericValueOutOfRange) integer out of range`

**Cause:** Le Telegram user ID `6500527972` dépasse la limite d'un `INTEGER` PostgreSQL:
- **Limite INTEGER:** -2,147,483,648 à 2,147,483,647
- **User ID reçu:** 6,500,527,972 ❌

## Solution appliquée

### 1. ✅ Modèle corrigé (`core/database/models.py`)

**Avant:**
```python
telegram_user_id = Column(Integer, unique=True, nullable=False, index=True)
```

**Après:**
```python
telegram_user_id = Column(BigInteger, unique=True, nullable=False, index=True)
```

### 2. ✅ Migration SQL appliquée

Migration créée et appliquée sur Supabase:
- `migrations/fix_telegram_user_id_bigint.sql`
- Colonne `telegram_user_id` changée de `INTEGER` à `BIGINT`
- Index recréé

**Limites:**
- **INTEGER:** -2,147,483,648 à 2,147,483,647
- **BIGINT:** -9,223,372,036,854,775,808 à 9,223,372,036,854,775,807 ✅

## Comparaison avec l'ancien code

**Ancien code** (`telegram-bot-v2`):
```python
telegram_user_id = Column(BigInteger, primary_key=True, index=True)
```

**Nouveau code** (corrigé):
```python
telegram_user_id = Column(BigInteger, unique=True, nullable=False, index=True)
```

Note: Le nouveau code utilise un `id` séparé comme clé primaire, ce qui est une meilleure pratique pour les relations.

## Test

Après la migration, le bot devrait pouvoir créer des utilisateurs avec des Telegram user IDs de n'importe quelle taille.

**Test:**
1. Relancer le bot
2. Envoyer `/start` dans Telegram
3. Vérifier que l'utilisateur est créé sans erreur

## Fichiers modifiés

1. `core/database/models.py` - Changement de type Integer → BigInteger
2. `migrations/fix_telegram_user_id_bigint.sql` - Migration SQL créée
3. Migration appliquée sur Supabase project `xxzdlbwfyetaxcmodiec`
