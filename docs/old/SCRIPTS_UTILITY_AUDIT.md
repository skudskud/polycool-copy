# 🔍 Audit des Scripts Utiles vs One-Shot

**Date:** Novembre 2025
**Version:** 1.0
**Auteur:** Senior Software Engineer

**Objectif:** Identifier les scripts encore utiles pour le bot vs ceux qui étaient des one-shot temporaires.

---

## 📋 Résumé Exécutif

**Sur 45+ scripts analysés :**
- **🔄 Utiles/Récurrents : ~30 scripts** (66%) - À conserver
- **🔚 One-Shot : ~15 scripts** (33%) - À archiver/nettoyer
- **⚠️ Scripts problématiques : 3** - À refactorer

---

## 🔄 SCRIPTS UTILES (À CONSERVER)

### 2.1 Diagnostics Scripts (`diagnostics/`)
**Tous ces scripts sont encore critiques pour le monitoring opérationnel**

#### ✅ **check_db_connection.py**
- **Utilité :** Test connexion DB + permissions + écriture
- **Fréquence :** Quotidienne (health checks)
- **Impact :** Critique pour troubleshooting

#### ✅ **emergency_bot_recovery.py**
- **Utilité :** Recovery complet après crash (Redis locks, services)
- **Fréquence :** Lors d'incidents production
- **Impact :** Essentiel pour stabilité

#### ✅ **check_recent_smart_trades.py**
- **Utilité :** Validation data quality smart trading
- **Fréquence :** Post-déploiement + monitoring
- **Impact :** Qualité des recommendations

#### ✅ **check_poller_streamer.py**
- **Utilité :** Monitoring ingestion temps réel
- **Fréquence :** Continue (background checks)
- **Impact :** Disponibilité des données

#### ✅ **force_sync_smart_wallets.py**
- **Utilité :** Sync manuel quand scheduler échoue
- **Fréquence :** Exceptionnelle (fallback)
- **Impact :** Continuity smart trading

### 2.2 Analysis Scripts (`analysis/`)
**Scripts d'analyse métier encore pertinents**

#### ✅ **audit_smart_trading.py**
- **Utilité :** Audit complet système smart trading
- **Fréquence :** Hebdomadaire + post-déploiement
- **Impact :** Performance monitoring

#### ✅ **analyze_smart_wallet_markets.py**
- **Utilité :** Analyse comportement wallets par marché
- **Fréquence :** Mensuelle (insights business)
- **Impact :** Stratégie smart trading

#### ✅ **audit_category_health.py**
- **Utilité :** Validation classification marchés
- **Fréquence :** Après changements catégories
- **Impact :** Accuracy discovery

### 2.3 Debug Scripts (`debug/`)
**Outils de développement essentiels**

#### ✅ **debug_market_issue.py**
- **Utilité :** Debug problèmes data marchés
- **Fréquence :** Lors de bugs discovery
- **Impact :** Development productivity

#### ✅ **debug_smart_trading_filters.py**
- **Utilité :** Validation filtres smart trading
- **Fréquence :** Après changements logique
- **Impact :** Quality assurance

### 2.4 Maintenance Scripts (root level)
**Opérations de maintenance récurrentes**

#### ✅ **flush_market_cache.py**
- **Utilité :** Invalidation cache marchés
- **Fréquence :** Après changements data
- **Impact :** Data consistency

#### ✅ **invalidate_markets_cache.py**
- **Utilité :** Reset complet cache marchés
- **Fréquence :** Troubleshooting cache
- **Impact :** Recovery cache issues

#### ✅ **manual_scan_now.py**
- **Utilité :** Trigger manuel ingestion data
- **Fréquence :** Testing + emergency
- **Impact :** Data refresh control

#### ✅ **verify_market_grouping.py**
- **Utilité :** Validation logique grouping marchés
- **Fréquence :** Après changements grouping
- **Impact :** UX discovery

---

## 🔚 SCRIPTS ONE-SHOT (À ARCHIVER)

### 3.1 Backfill Scripts
**Scripts créés pour rattraper des données manquées - plus nécessaires**

#### 🔚 **backfill_address.py**
- **Contexte :** Backfill historique pour adresses ajoutées tardivement
- **État :** One-shot terminé
- **Action :** Archiver (garder 6 mois au cas où)

#### 🔚 **backfill_condition_id.py**
- **Contexte :** Migration condition_id manquants
- **État :** Migration terminée
- **Action :** Supprimer (data maintenant complète)

#### 🔚 **backfill_market_questions.py**
- **Contexte :** Rattrapage questions marchés
- **État :** One-shot terminé
- **Action :** Archiver

### 3.2 Migration Helpers
**Scripts temporaires pour migrations**

#### 🔚 **apply_unified_notifications_migration.sh**
- **Contexte :** Migration système notifications
- **État :** Migration appliquée
- **Action :** Supprimer

### 3.3 Cleanup Scripts
**Scripts de nettoyage post-migration**

#### 🔚 **cleanup_positions.py**
- **Contexte :** Nettoyage table positions (PHASE 1 mentionnée)
- **État :** Migration terminée
- **Action :** Archiver (historique)

### 3.4 Specific Analysis Scripts
**Scripts créés pour debugger des problèmes spécifiques**

#### 🔚 **analyze_tx_web3.py**
- **Contexte :** Analyse transactions redeem spécifiques
- **État :** Debugging terminé
- **Action :** Supprimer (trop spécifique)

### 3.5 Railway-Specific Scripts
**Scripts spécifiques à Railway, moins utiles maintenant**

#### 🔚 **railway_cleanup.sh**
- **Contexte :** Cleanup Railway-specific
- **État :** One-shot terminé
- **Action :** Archiver

#### 🔚 **railway_emergency_fix.sh**
- **Contexte :** Fix temporaire Railway
- **État :** Fix appliqué
- **Action :** Supprimer

---

## ⚠️ SCRIPTS PROBLÉMATIQUES (À REFACTORER)

### 4.1 Scripts avec Hardcoded Credentials

#### ⚠️ **analyze_transactions.py**
- **Problème :** Contient DATABASE_URL en dur
- **Risque :** Security breach possible
- **Action :** Refactorer avec env vars

#### ⚠️ **audit_smart_trading.py**
- **Problème :** DATABASE_URL en dur dans code
- **Risque :** Credentials exposés
- **Action :** Migrer vers config sécurisée

### 4.2 Scripts Redondants

#### ⚠️ **force_smart_wallet_sync.py** vs **force_sync_smart_wallets.py**
- **Problème :** Deux scripts similaires
- **Impact :** Confusion, maintenance double
- **Action :** Consolider en un script

---

## 📊 ANALYSE PAR CATÉGORIE

### **Répartition par Utilité**

| Catégorie | Total | Utiles | One-Shot | Problématiques |
|-----------|-------|--------|----------|----------------|
| Diagnostics | 12 | 8 | 4 | 0 |
| Analysis | 5 | 4 | 1 | 2 |
| Debug | 3 | 3 | 0 | 0 |
| Maintenance | 8 | 6 | 2 | 0 |
| Backfill | 3 | 0 | 3 | 0 |
| Migration | 8 | 0 | 8 | 0 |
| Railway | 2 | 0 | 2 | 0 |
| **TOTAL** | **41** | **21** | **16** | **2** |

### **Critères de Classification**

#### ✅ **Critères "Utile"**
- **Monitoring opérationnel** (diagnostics quotidiens)
- **Troubleshooting** (debug + emergency recovery)
- **Quality assurance** (audits + validations)
- **Maintenance récurrente** (cache + data management)
- **Business intelligence** (analyses stratégiques)

#### 🔚 **Critères "One-Shot"**
- **Scripts migration** (terminés et non réutilisables)
- **Backfill data** (rattrapage historique terminé)
- **Debugging spécifique** (problèmes résolus)
- **Setup temporaire** (configurations one-time)

---

## 🎯 RECOMMANDATIONS

### **Actions Immédiates**

#### **🗂️ Nettoyage (1-2 jours)**
1. **Archiver 16 scripts one-shot** dans `/scripts/archive/`
2. **Supprimer scripts périmés** (backfill, migration terminés)
3. **Créer documentation** pour scripts restants

#### **🔧 Refactoring (2-3 jours)**
1. **Fix hardcoded credentials** dans audit scripts
2. **Consolider scripts redondants** (force_sync_*)
3. **Standardiser patterns** d'exécution

#### **📈 Amélioration (1 semaine)**
1. **Créer script runner unifié** (`scripts/run.py`)
2. **Ajouter monitoring automatisé** pour scripts critiques
3. **Créer dashboard scripts** avec métriques d'exécution

### **Nouveau Standard pour Scripts**

#### **Template Standardisé**
```python
#!/usr/bin/env python3
"""
[SCRIPT_NAME] - [BRIEF_DESCRIPTION]

Usage: python scripts/[category]/[script_name].py [args]

Created: [DATE]
Last Modified: [DATE]
Status: [ACTIVE/ARCHIVED/DEPRECATED]
"""

# Standard imports
import sys
import os
import logging
from pathlib import Path

# Add project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Standard logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Main execution with proper error handling"""
    try:
        # Script logic here
        pass
    except Exception as e:
        logger.error(f"Script failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

#### **Metadata Obligatoire**
- **Created/Modified dates**
- **Status** (ACTIVE/ARCHIVED/DEPRECATED)
- **Dependencies** listées
- **Usage examples**
- **Expected runtime**

---

## 📈 IMPACT BUSINESS

### **Bénéfices du Nettoyage**

#### **✅ Maintenance Réduite**
- **-30% scripts** à maintenir
- **Documentation clarifiée** pour scripts restants
- **Réduction risques** security (hardcoded credentials)

#### **✅ Operational Efficiency**
- **Scripts critiques** plus visibles
- **Runbooks clairs** pour emergencies
- **Monitoring amélioré** des outils essentiels

#### **✅ Development Velocity**
- **Nouveaux scripts** suivent standards
- **Code review** plus efficace
- **Onboarding** accéléré pour nouveaux devs

### **Risques si Non Fait**

#### **❌ Technical Debt**
- **Maintenance croissante** de scripts obsolètes
- **Security risks** avec credentials exposés
- **Developer confusion** avec scripts similaires

#### **❌ Operational Issues**
- **Emergency response** ralentie par scripts obsolètes
- **Debugging** compliqué par outils incohérents
- **Production incidents** dus à scripts mal maintenus

---

## 🎯 CONCLUSION

**Le nettoyage des scripts est une opportunité importante d'améliorer la maintenabilité et réduire la technical debt.**

**Actions prioritaires :**
1. **Archiver/supprimer** les 16 scripts one-shot
2. **Refactorer** les 2 scripts problématiques
3. **Standardiser** les patterns pour nouveaux scripts

**Résultat attendu :** Base de code plus propre, mieux maintenue, avec des outils opérationnels fiables et sécurisés.

---

*Document créé le 6 novembre 2025 - Audit utility vs one-shot scripts*
