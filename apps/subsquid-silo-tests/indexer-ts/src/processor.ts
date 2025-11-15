import {assertNotNull} from '@subsquid/util-internal'
import {
    BlockHeader,
    DataHandlerContext,
    EvmBatchProcessor,
    EvmBatchProcessorFields,
    Log as _Log,
    Transaction as _Transaction,
} from '@subsquid/evm-processor'

export const processor = new EvmBatchProcessor()
    // Polygon mainnet archive - handles both archive AND live blocks
    .setGateway('https://v2.archive.subsquid.io/network/polygon-mainnet')
    // ⚠️ CRITICAL: Add RPC endpoint for LIVE block processing
    // Without this, processor stops after backfill (no way to get new blocks)
    // With RPC, it can stay open and process new blocks indefinitely
    .setRpcEndpoint({
      // Support both RPC_POLYGON_HTTP and POLYGON_RPC_URL for flexibility
      url: process.env.RPC_POLYGON_HTTP || process.env.POLYGON_RPC_URL || 'https://polygon-rpc.com',
      rateLimit: 25  // ⚡ OPTIMIZED: Max free tier Alchemy (was 10)
    })
    .setFinalityConfirmation(50)  // ⚡ OPTIMIZED: Reduced from 75 to 50 blocks (-50s latency)
    .setFields({
        transaction: {
            from: true,
            to: true,
            hash: true,
        },
    })
    .setBlockRange({
        // Start from very recent block (skip backfill)
        from: 78820000,  // ~current block height - skip old backfill
    })
    // Listen for TransferSingle events from MULTIPLE Conditional Tokens contracts
    // This covers different Conditional Tokens implementations used by Polymarket
    .addLog({
        address: [
            '0x4D97DCd97eC945f40cF65F87097ACe5EA0476045', // Main Conditional Tokens contract
            '0xCeAfDD6Bc0bEF976fdCd1112955828E00543c0Ce5', // Alternative Conditional Tokens
            // Add more contracts as discovered...
        ],
        // TransferSingle(address indexed operator, address indexed from, address indexed to, uint256 id, uint256 value)
        topic0: ['0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62'],
        transaction: true,
    })
    // Listen for TransferBatch events from MULTIPLE Conditional Tokens contracts
    .addLog({
        address: [
            '0x4D97DCd97eC945f40cF65F87097ACe5EA0476045', // Main Conditional Tokens contract
            '0xCeAfDD6Bc0bEF976fdCd1112955828E00543c0Ce5', // Alternative Conditional Tokens
            // Add more contracts as discovered...
        ],
        // TransferBatch(address indexed operator, address indexed from, address indexed to, uint256[] ids, uint256[] values)
        topic0: ['0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07ce33e6397d8d63df03e93'],
        transaction: true,
    })

    // Listen for USDC transfers to capture exact trade amounts
    .addLog({
        address: ['0x2791bca1f2de4661ed88a30c99a7a9449aa84174'], // USDC contract on Polygon
        // Transfer(address indexed from, address indexed to, uint256 value)
        topic0: ['0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'],
        transaction: true,
    })

export type Fields = EvmBatchProcessorFields<typeof processor>
export type Block = BlockHeader<Fields>
export type Log = _Log<Fields>
export type Transaction = _Transaction<Fields>
export type ProcessorContext<Store> = DataHandlerContext<Store, Fields>

// ⚠️ FIX #4: Add connection pool monitoring
// Log pool stats every 30 seconds during backfill
export function startPoolMonitoring(db: any): void {
  if (!db.getPool) {
    console.log('[POOL] TypeormDatabase does not expose pool monitoring')
    return
  }

  const pool = db.getPool?.()
  if (!pool) {
    console.log('[POOL] Could not access connection pool')
    return
  }

  setInterval(() => {
    try {
      const totalCount = pool.totalCount || 0
      const idleCount = pool.idleCount || 0
      const waitingCount = pool.waitingCount || 0
      const activeCount = totalCount - idleCount

      console.log('[POOL] Connection Pool Status:')
      console.log(`[POOL]   Total: ${totalCount}, Active: ${activeCount}, Idle: ${idleCount}, Waiting: ${waitingCount}`)

      if (waitingCount > 5) {
        console.warn(`[POOL] ⚠️  High queue: ${waitingCount} queries waiting for connection`)
      }
    } catch (e) {
      // Pool monitoring not available in this version
    }
  }, 30000)
}
