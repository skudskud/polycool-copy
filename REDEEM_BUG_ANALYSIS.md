# 🔍 Analyse du Bug de Redemption

**Date:** 5 Novembre 2025
**Status:** ✅ RÉSOLU (code déjà fixé)

## 📊 Transactions Analysées

### ❌ Transaction Échouée (Mon Bot)
- **TX Hash:** `0x1a05d029e973a4d6a38565bd34bac95d25e84a5ae0811efd0077c2a59023c785`
- **Market:** Bitcoin Up or Down - November 4, 12:30PM-12:45PM ET
- **User Wallet:** `0xE235db7fcbc64161028eFbc0E131852188d8f11D`
- **Contrat Appelé:** `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` ← **CTF_EXCHANGE (MAUVAIS)**
- **Gas Limit:** 300,000
- **Gas Utilisé:** 25,080 (8.4%) ← Échec rapide = revert
- **Block:** 78618113
- **Statut:** FAILED

### ✅ Transaction Réussie (Concurrent)
- **TX Hash:** `0x360198d0964a7c6b0bc4130b95fd435f2a4aedc4b1d9ce8787beacaf6f46d272`
- **Market:** Bitcoin Up or Down - November 5, 6:45AM-7:00AM ET
- **User Wallet:** `0x0D2047BC43BBDe1EC1C8009f57679Ae6F454322f`
- **Contrat Appelé:** `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` ← **CONDITIONAL_TOKENS (BON)**
- **Gas Limit:** 125,066
- **Gas Utilisé:** 94,700 (75.7%) ← Exécution complète
- **Block:** 78619601
- **Statut:** SUCCESS

## 🎯 Problème Identifié

### Ce que j'ai trouvé :
1. **Mauvais contrat utilisé** : Le bot appelait `CTF_EXCHANGE` au lieu de `CONDITIONAL_TOKENS`
2. **Gas suffisant** : Le bot avait 300,000 gas (plus que nécessaire!)
3. **Revert immédiat** : Seulement 25,080 gas utilisé = échec rapide

### Ce n'était PAS un problème de gas
- Mon bot : 300,000 gas limit ❌ FAILED
- Concurrent : 125,066 gas limit ✅ SUCCESS

Le problème était le **mauvais contrat**, pas le gas !

## ✅ Solution (Déjà Implémentée)

Le code actuel dans `redemption_service.py` utilise déjà le bon contrat :

```python
# Ligne 229
CONDITIONAL_TOKENS_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
conditional_tokens = w3.eth.contract(
    address=w3.to_checksum_address(CONDITIONAL_TOKENS_ADDRESS),
    abi=CONDITIONAL_TOKENS_ABI
)
```

## 📝 État de la DB

Position dans `resolved_positions` (id=12):
```json
{
  "market_id": "664763",
  "condition_id": "0x380e8abd804001d104f625a15d8ca46e0dc3ffa88db654bfba16b90fa84d5d85",
  "market_title": "Bitcoin Up or Down - November 4, 12:30PM-12:45PM ET",
  "outcome": "YES",
  "token_id": "113489127166554764847989030371990042559435970288618303388641384649634912416256",
  "tokens_held": "3.22580500",
  "winning_outcome": "YES",
  "is_winner": true,
  "status": "PENDING",
  "redemption_tx_hash": null,
  "last_redemption_error": "(\"The function 'redeemPositions' was not found in this \", \"contract's abi.\")",
  "redemption_attempt_count": 8
}
```

**Note:** L'erreur dans `last_redemption_error` provient d'une ancienne tentative avec le mauvais code.

## 🔧 Prochaines Étapes

1. ✅ Code corrigé (utilise CONDITIONAL_TOKENS)
2. ⏳ Tester le redeem avec le code actuel
3. ⏳ Vérifier que le market est bien résolu on-chain
4. ⏳ Retenter le redeem pour la position id=12

## 📚 Références

- Conditional Tokens Contract: `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`
- CTF Exchange (à ne PAS utiliser): `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`
- Method ID: `0x26c41411` = `redeemPositions(address,bytes32,bytes32,uint256[])`

## ⚠️ Important

Le mauvais contrat (`CTF_EXCHANGE`) n'est **PAS** le même que `CONDITIONAL_TOKENS`. Il faut toujours utiliser le contrat `CONDITIONAL_TOKENS` pour redeem :
- ✅ Bon: `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` (CONDITIONAL_TOKENS)
- ❌ Mauvais: `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` (CTF_EXCHANGE)
