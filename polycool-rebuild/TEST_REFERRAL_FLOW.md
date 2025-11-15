# Test du Flux Referral avec Curl

## 🔍 État Actuel de la Base de Données

### Users
- **User ID 1** : `kalzerinho` (telegram_user_id: 6500527972) - ✅ **referral_code généré: 'kalzerinho'**
- **User ID 3** : `test_user` (telegram_user_id: 123456789)
- **User ID 4** : (telegram_user_id: 863767564, username: null)

### Referrals
- ✅ **1 referral créé manuellement** pour test :
  - Referrer: kalzerinho (id=1)
  - Referred: test_user (id=3)
  - Level: 1

## ⚠️ Problème Identifié

L'API ne trouve pas les users via `get_by_telegram_id` à cause d'une erreur SQLAlchemy :
```
Mapper 'Mapper[User(users)]' has no property 'resolved_positions'
```

Cela empêche l'endpoint `/referral/create` de fonctionner car il ne peut pas récupérer le `referred_user`.

## ✅ Corrections Appliquées

### 1. Fallback par Username
Le service `referral_service.create_referral()` cherche maintenant :
1. D'abord par `referral_code` exact
2. Si pas trouvé, par `username` (case-insensitive)
3. Génère automatiquement le `referral_code` si trouvé par username mais code manquant

### 2. Génération du Referral Code
- ✅ `kalzerinho` a maintenant `referral_code = 'kalzerinho'` dans la DB

### 3. Test Direct dans la DB
- ✅ Un referral a été créé manuellement pour vérifier que la structure fonctionne

## 🧪 Tests à Effectuer

### Test 1: Vérifier que le referral_code fonctionne
```bash
# Le code "kalzerinho" devrait maintenant être trouvé
curl -X POST http://localhost:8000/api/v1/referral/create \
  -H "Content-Type: application/json" \
  -d '{"referrer_code": "kalzerinho", "referred_telegram_user_id": 123456789}'
```

**Résultat attendu** :
- Si l'API trouve le user → Succès
- Si l'API ne trouve pas le user → Erreur "Referred user not found" (problème SQLAlchemy)

### Test 2: Vérifier les stats de referral
```bash
curl http://localhost:8000/api/v1/referral/stats/telegram/6500527972 | jq .
```

**Résultat attendu** : Stats avec 1 referral au niveau 1

### Test 3: Vérifier la liste des referrals
```bash
curl http://localhost:8000/api/v1/referral/referrals/1 | jq .
```

**Résultat attendu** : Liste avec test_user

## 🔧 Problème à Résoudre

### Erreur SQLAlchemy
L'API a un problème avec les modèles SQLAlchemy qui empêche `get_by_telegram_id` de fonctionner.

**Solution** : Vérifier les modèles dans `core/database/models.py` et s'assurer que la relation `resolved_positions` est correctement définie ou supprimée si elle n'existe pas.

## 📊 État Actuel

✅ **Ce qui fonctionne** :
- La structure de la table `referrals` est correcte
- Le `referral_code` est généré pour kalzerinho
- Un referral peut être créé directement dans la DB
- Le service de referral a le fallback par username

❌ **Ce qui ne fonctionne pas** :
- L'API ne peut pas récupérer les users (erreur SQLAlchemy)
- L'endpoint `/referral/create` échoue car il ne trouve pas le `referred_user`

## 🎯 Prochaines Étapes

1. **Corriger l'erreur SQLAlchemy** dans les modèles
2. **Tester à nouveau** l'endpoint `/referral/create` avec curl
3. **Vérifier** que le flux complet fonctionne depuis le bot

## 📝 Notes

Le code de referral "kalzerinho" est maintenant dans la DB et devrait fonctionner une fois que le problème SQLAlchemy sera résolu. Le fallback par username permettra aussi de trouver kalzerinho même si le code n'était pas généré.
