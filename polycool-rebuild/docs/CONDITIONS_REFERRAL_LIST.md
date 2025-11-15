# Conditions pour voir un référé dans la liste

## 📋 Conditions Requises

Pour qu'un référé apparaisse dans la liste du parrain (`/referral` → "📋 My Referrals"), **une seule condition est nécessaire** :

### ✅ Condition Unique

**Une relation referral doit exister dans la table `referrals`** avec :
- `referrer_user_id` = ID interne du parrain
- `referred_user_id` = ID interne du référé
- `level` = 1, 2 ou 3 (niveau de la relation)

## 🔄 Comment la relation est créée

La relation referral est créée automatiquement quand :

1. **Un utilisateur utilise `/start` avec un code de referral**
   - Exemple : `/start username` ou `/start referral_code`
   - Le code est extrait des arguments de la commande

2. **Le code de referral est valide**
   - Le code doit exister dans `users.referral_code`
   - Peut être un username ou un code généré

3. **L'utilisateur n'est pas déjà référé**
   - Contrainte unique : un utilisateur ne peut être référé qu'une fois
   - Si l'utilisateur a déjà un parrain, la relation n'est pas créée

4. **L'utilisateur ne se réfère pas lui-même**
   - Vérification que `referrer_id != referred_user_id`

## 📊 Affichage dans la liste

La requête SQL pour récupérer la liste des référés :

```sql
SELECT Referral.*, User.username
FROM referrals Referral
JOIN users User ON Referral.referred_user_id = User.id
WHERE Referral.referrer_user_id = :user_id
```

**Ce qui est affiché :**
- Username du référé (ou "Unknown" si username est NULL)
- Niveau de la relation (1, 2 ou 3)
- Date de création de la relation

**Limite d'affichage :**
- Maximum 10 référés par niveau dans l'interface
- Si plus de 10, affiche "... and X more"

## ⚠️ Points Importants

### 1. Pas de condition sur l'activité
- **Le référé n'a pas besoin d'être actif**
- **Le référé n'a pas besoin d'avoir fait de trades**
- **Le référé n'a pas besoin d'avoir un wallet financé**

### 2. La relation est créée immédiatement
- Dès que l'utilisateur utilise `/start` avec un code de referral valide
- Avant même qu'il complète l'onboarding
- Avant même qu'il finance son wallet

### 3. Système 3 niveaux automatique
Quand un utilisateur est référé :
- **Niveau 1** : Relation directe avec le parrain (créée automatiquement)
- **Niveau 2** : Relation avec le parrain du parrain (si existe, créée automatiquement)
- **Niveau 3** : Relation avec le parrain du parrain du parrain (si existe, créée automatiquement)

### 4. Username optionnel
- Si le référé n'a pas de username Telegram, il apparaît comme "Unknown"
- Mais il apparaît quand même dans la liste

## 🔍 Vérification dans la base de données

Pour vérifier si une relation existe :

```sql
SELECT
    r.id,
    r.referrer_user_id,
    r.referred_user_id,
    r.level,
    r.created_at,
    u1.username as referrer_username,
    u2.username as referred_username
FROM referrals r
LEFT JOIN users u1 ON r.referrer_user_id = u1.id
LEFT JOIN users u2 ON r.referred_user_id = u2.id
WHERE r.referrer_user_id = :votre_user_id;
```

## 📝 Exemple de Flux

1. **Parrain A** partage son lien : `t.me/Polypolis_Bot?start=username_A`
2. **Utilisateur B** clique sur le lien et utilise `/start username_A`
3. **Système** :
   - Vérifie que `username_A` existe comme `referral_code`
   - Vérifie que B n'est pas déjà référé
   - Crée la relation : `referrer_user_id = A.id`, `referred_user_id = B.id`, `level = 1`
   - Si A a un parrain C, crée aussi : `referrer_user_id = C.id`, `referred_user_id = B.id`, `level = 2`
   - Si C a un parrain D, crée aussi : `referrer_user_id = D.id`, `referred_user_id = B.id`, `level = 3`
4. **Résultat** : B apparaît immédiatement dans la liste de A (niveau 1), C (niveau 2), et D (niveau 3)

## ✅ Résumé

**Condition unique pour voir un référé :**
- Une entrée dans la table `referrals` avec `referrer_user_id` = votre ID

**Pas de conditions supplémentaires :**
- ❌ Pas besoin que le référé soit actif
- ❌ Pas besoin que le référé ait fait des trades
- ❌ Pas besoin que le référé ait financé son wallet
- ❌ Pas besoin que le référé ait un username (apparaît comme "Unknown")

**La relation est créée dès que :**
- L'utilisateur utilise `/start` avec votre code de referral
- Le code est valide
- L'utilisateur n'est pas déjà référé
