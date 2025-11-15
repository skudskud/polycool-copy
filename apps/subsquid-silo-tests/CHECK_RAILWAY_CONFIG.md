# 🔍 Comment vérifier votre configuration Railway

## Option 1: Via Railway Dashboard (Web)

1. Allez sur https://railway.app
2. Sélectionnez votre projet
3. Cliquez sur le service **"Data Ingestion"**
4. Allez dans l'onglet **"Variables"**
5. Vérifiez la valeur de `DATABASE_URL`

### ✅ Doit contenir:
```
postgresql://postgres:[PASSWORD]@db.fkksycggxaaohlfdwfle.supabase.co:5432/postgres
                                    ^^^^^^^^^^^^^^^^^^^^^^
                                    polycool v2 europe (EU West)
```

### ❌ Ne doit PAS contenir:
```
postgresql://postgres:[PASSWORD]@db.gvckzwmuuyrlcyjmgdpo.supabase.co:5432/postgres
                                    ^^^^^^^^^^^^^^^^^^^^^^
                                    skudskud's Project (US East)
```

---

## Option 2: Via Railway CLI

```bash
# Login si nécessaire
railway login

# Lister les projets
railway list

# Linker au bon projet
railway link

# Voir les variables du service Data Ingestion
railway variables --service "Data Ingestion"
```

Cherchez la ligne `DATABASE_URL` et vérifiez l'host.

---

## Option 3: Vérifier les logs

```bash
# Voir les 100 dernières lignes de logs
railway logs --service "Data Ingestion" | tail -100

# Chercher les messages TIER 0
railway logs --service "Data Ingestion" | grep "TIER 0"
```

### Ce que vous DEVEZ voir si tout fonctionne:
```
✅ Poller service starting...
🚨🚨🚨 [TIER 0 DEBUG] get_user_position_market_ids() returned 44 markets: ['628803', '619189', '665974', ...]
🎯 [TIER 0: USER_POSITIONS] Polling 44 markets with active positions
✅ [TIER 0] Updated 44 user position markets for fast resolution detection
```

### Si vous voyez une erreur:
```
❌ column sp.resolution_status does not exist
→ Mauvaise base de données (gvckzwmuuyrlcyjmgdpo au lieu de fkksycggxaaohlfdwfle)

❌ No services enabled
→ POLLER_ENABLED n'est pas à true

❌ EXPERIMENTAL_SUBSQUID not enabled
→ La variable EXPERIMENTAL_SUBSQUID n'est pas définie
```

---

## Option 4: Vérifier directement dans Supabase

Quel est le projet Supabase utilisé par votre production?

1. **`fkksycggxaaohlfdwfle`** (polycool v2 europe - EU West)
   - ✅ A `resolution_status`
   - ✅ A votre market 665974
   - ✅ **C'est celui qu'il faut utiliser!**

2. **`gvckzwmuuyrlcyjmgdpo`** (skudskud's Project - US East)
   - ❌ Pas de market 665974
   - ⚠️ Ne devrait pas être utilisé pour ce projet

---

## 🚀 Commandes rapides

```bash
# Vérifier quelle base de données est utilisée
railway run --service "Data Ingestion" env | grep DATABASE_URL

# Voir les logs en temps réel
railway logs --service "Data Ingestion" --follow

# Redéployer le service
railway up --service "Data Ingestion"
```

---

## 📝 Checklist

- [ ] `DATABASE_URL` pointe vers `db.fkksycggxaaohlfdwfle.supabase.co`
- [ ] `REDIS_URL` est défini
- [ ] `EXPERIMENTAL_SUBSQUID=true`
- [ ] `POLLER_ENABLED=true` (ou non défini, défaut true)
- [ ] Les logs montrent "🚨🚨🚨 [TIER 0 DEBUG]"
- [ ] Le market 665974 apparaît dans la liste TIER 0

---

## ⚡ Action immédiate

Envoyez-moi:
1. La valeur de `DATABASE_URL` (vous pouvez masquer le mot de passe)
2. Ou les premiers logs au démarrage du service

Pour obtenir les logs:
```bash
railway logs --service "Data Ingestion" --limit 50
```
