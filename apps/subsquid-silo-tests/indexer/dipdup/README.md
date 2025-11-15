# DipDup On-Chain Indexer for PolyMarket

Indexes Conditional Tokens transfers and payouts on Polygon, storing fills and user transactions in Supabase.

## Setup

### 1. Install DipDup CLI
```bash
pip install dipdup
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env:
# DATABASE_HOST=your-supabase-host
# DATABASE_USER=your-user
# DATABASE_PASSWORD=your-password
# POLYGON_RPC_URL=https://polygon-rpc.com
```

### 3. Initialize Project
```bash
dipdup init
```

### 4. Run Indexer
```bash
dipdup run
```

## Architecture

### Handlers

| Event | Table | Description |
|-------|-------|-------------|
| Transfer | subsquid_fills_onchain | Single token transfer (fills) |
| TransferBatch | subsquid_user_transactions | Batch transfers (user txs) |
| PayoutRedeemed | subsquid_events | Market settlement/redemption |

### Contract

- **Conditional Tokens:** `0xd5524179cb7ae012f5b642c1d6d700a289d07fb3`
- **Network:** Polygon (137)
- **Events:**
  - Transfer(indexed operator, indexed from, indexed to, id, value)
  - TransferBatch(indexed operator, indexed from, indexed to, ids[], values[])
  - PayoutRedeemed(indexed redeemer, indexed conditionId, indexed indexSet, payout)

## Data Flow

```
Polygon RPC
    ↓
DipDup Event Stream
    ↓
handlers/transfers.py
  ├─ on_transfer → subsquid_fills_onchain
  ├─ on_transfer_batch → subsquid_user_transactions
  └─ handlers/payouts.py
       └─ on_payout_redeemed → subsquid_events
    ↓
Supabase Database (isolated tables)
```

## Testing Locally

```bash
# Mock event with dipdup test framework
dipdup test handlers/transfers.py::test_on_transfer

# Run on testnet (Polygon Mumbai)
POLYGON_RPC_URL=https://rpc-mumbai.maticvigil.com dipdup run
```

## Production Deployment

See Railway deployment guide in `../../README.md`

## Monitoring

DipDup provides built-in metrics:
- `dipdup_indexer_blocks_processed_total`
- `dipdup_indexer_events_processed_total`
- `dipdup_indexer_synced_blocks_current`

View metrics at: `http://localhost:8000/metrics` (if enabled)

## Troubleshooting

### Reindex from Block N
```bash
dipdup hasura set-status indexer ${N}
```

### Reset Database
```bash
dipdup create
```

### Check Logs
```bash
dipdup logs -f
```

## References

- [DipDup Docs](https://docs.dipdup.io/)
- [Conditional Tokens](https://ctf.polymarket.com/)
- [EVM Processor](https://docs.dipdup.io/evm-processor/)
