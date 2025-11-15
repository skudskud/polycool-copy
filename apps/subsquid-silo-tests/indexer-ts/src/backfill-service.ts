/**
 * Backfill Service
 *
 * Fetches historical transactions for newly added watched addresses
 * Prevents data loss when addresses are added after their trades occurred
 */

import { DataSource } from 'typeorm';
import { UserTransaction } from './model';
import { parseTransferEvent, parseTransferBatchEvent, extractMarketIdAndOutcome } from './abi/multicall';

const TRANSFER_SINGLE_TOPIC = '0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62';
const TRANSFER_BATCH_TOPIC = '0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07ce33e6397d8d63df03e93';
const CONDITIONAL_TOKENS_ADDRESS = '0x4D97DCd97eC945f40cF65F87097ACe5EA0476045';

interface BackfillConfig {
  rpcUrl: string;
  lookbackHours: number; // How many hours to look back (default: 2)
}

export class BackfillService {
  private rpcUrl: string;
  private lookbackHours: number;

  constructor(config: BackfillConfig) {
    this.rpcUrl = config.rpcUrl;
    this.lookbackHours = config.lookbackHours || 2;
  }

  /**
   * Estimate how many blocks to look back based on hours
   * Polygon: ~2.1 seconds per block average
   */
  private getBlocksToLookBack(): number {
    const secondsPerBlock = 2.1;
    const secondsToLookBack = this.lookbackHours * 60 * 60;
    return Math.floor(secondsToLookBack / secondsPerBlock);
  }

  /**
   * Backfill transactions for a newly added address
   *
   * @param address - Ethereum address to backfill
   * @param currentBlock - Current block number
   * @param db - TypeORM DataSource
   */
  async backfillAddress(address: string, currentBlock: number, db: any): Promise<number> {
    const blocksToLookBack = this.getBlocksToLookBack();
    const fromBlock = Math.max(0, currentBlock - blocksToLookBack);

    console.log(`[BACKFILL] 🔄 Starting backfill for ${address.slice(0, 10)}... (${fromBlock} → ${currentBlock}, ${blocksToLookBack} blocks, ~${this.lookbackHours}h)`);

    try {
      // Query RPC for logs involving this address
      const logs = await this.fetchLogsForAddress(address, fromBlock, currentBlock);

      if (logs.length === 0) {
        console.log(`[BACKFILL] No historical transactions found for ${address}`);
        return 0;
      }

      console.log(`[BACKFILL] Found ${logs.length} historical logs for ${address}`);

      // Parse logs and create UserTransaction entries
      const transactions = await this.parseLogsToTransactions(logs, address);

      if (transactions.length === 0) {
        console.log(`[BACKFILL] No valid transactions to insert`);
        return 0;
      }

      // Insert into database
      await db.createQueryBuilder()
        .insert()
        .into(UserTransaction)
        .values(transactions)
        .orIgnore() // Avoid duplicates if transaction already exists
        .execute();

      console.log(`[BACKFILL] ✅ Inserted ${transactions.length} historical transactions for ${address}`);
      return transactions.length;

    } catch (err: any) {
      console.error(`[BACKFILL] ❌ Error backfilling ${address}:`, err.message);
      return 0;
    }
  }

  /**
   * Fetch logs from RPC for a specific address
   */
  private async fetchLogsForAddress(address: string, fromBlock: number, toBlock: number): Promise<any[]> {
    console.log(`[BACKFILL] 📡 RPC call: ${fromBlock} → ${toBlock} for ${address.slice(0, 10)}...`);

    // Use eth_getLogs to fetch TransferSingle and TransferBatch events
    // where the address is either 'from' or 'to'

    const response = await fetch(this.rpcUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'eth_getLogs',
        params: [{
          fromBlock: `0x${fromBlock.toString(16)}`,
          toBlock: `0x${toBlock.toString(16)}`,
          address: CONDITIONAL_TOKENS_ADDRESS,
          topics: [
            [TRANSFER_SINGLE_TOPIC, TRANSFER_BATCH_TOPIC], // topic0: either event
            null, // topic1: operator (not filtered)
            null, // topic2: from OR
            null  // topic3: to
          ]
        }]
      })
    });

    const data = await response.json();

    if (data.error) {
      throw new Error(`RPC error: ${data.error.message}`);
    }

    const allLogs = data.result || [];
    console.log(`[BACKFILL] 📋 RPC returned ${allLogs.length} total logs`);

    // Filter logs to only include those involving our address
    const addressLower = address.toLowerCase();
    const filteredLogs = allLogs.filter((log: any) => {
      // Check if address appears in indexed topics (from/to)
      const topics = log.topics || [];
      for (let i = 1; i < topics.length; i++) {
        const topic = topics[i];
        if (topic && topic.toLowerCase().includes(addressLower.slice(2))) {
          return true;
        }
      }
      return false;
    });

    console.log(`[BACKFILL] 🎯 Filtered to ${filteredLogs.length} logs involving ${address.slice(0, 10)}...`);
    return filteredLogs;
  }

  /**
   * Parse raw logs into UserTransaction objects
   */
  private async parseLogsToTransactions(logs: any[], targetAddress: string): Promise<UserTransaction[]> {
    const transactions: UserTransaction[] = [];

    for (const log of logs) {
      try {
        const topic0 = log.topics[0];

        if (topic0 === TRANSFER_SINGLE_TOPIC) {
          const parsed = parseTransferEvent(log.topics, log.data);
          if (!parsed) continue;

          const { from, to, tokenId, amount } = parsed;

          // Determine if BUY or SELL
          const isBuy = from.toLowerCase() === '0x0000000000000000000000000000000000000000';
          const isSell = to.toLowerCase() === '0x0000000000000000000000000000000000000000';

          if (isSell) continue; // Ignore burns

          const txType = isBuy ? 'BUY' : 'SELL';
          const userAddress = isBuy ? to : from;

          // Only process if it's our target address
          if (userAddress.toLowerCase() !== targetAddress.toLowerCase()) {
            continue;
          }

          const { marketId, outcome } = extractMarketIdAndOutcome(tokenId);

          // Get block details for timestamp
          const blockNumber = parseInt(log.blockNumber, 16);
          const timestamp = await this.getBlockTimestamp(blockNumber);

          const userTx = new UserTransaction({
            id: `${log.transactionHash}-${log.logIndex}`,
            txId: `${log.transactionHash}_${log.logIndex}`,
            userAddress: userAddress.toLowerCase(),
            positionId: tokenId.toString(),
            marketId: marketId.toString(),
            outcome: outcome,
            txType: txType,
            amount: amount.toString(),
            price: null, // Will be enriched later
            amountInUsdc: null,
            txHash: log.transactionHash,
            blockNumber: BigInt(blockNumber),
            timestamp: new Date(timestamp * 1000),
          });

          transactions.push(userTx);

        } else if (topic0 === TRANSFER_BATCH_TOPIC) {
          const parsed = parseTransferBatchEvent(log.topics, log.data);
          if (!parsed) continue;

          const { from, to, tokenIds, amounts } = parsed;

          const isBuy = from.toLowerCase() === '0x0000000000000000000000000000000000000000';
          const isSell = to.toLowerCase() === '0x0000000000000000000000000000000000000000';

          if (isSell) continue;

          const txType = isBuy ? 'BUY' : 'SELL';
          const userAddress = isBuy ? to : from;

          if (userAddress.toLowerCase() !== targetAddress.toLowerCase()) {
            continue;
          }

          const blockNumber = parseInt(log.blockNumber, 16);
          const timestamp = await this.getBlockTimestamp(blockNumber);

          // Process each token in batch
          for (let i = 0; i < tokenIds.length; i++) {
            const tokenId = tokenIds[i];
            const amount = amounts[i];
            const { marketId, outcome } = extractMarketIdAndOutcome(tokenId);

            const userTx = new UserTransaction({
              id: `${log.transactionHash}-${log.logIndex}-${i}`,
              txId: `${log.transactionHash}_${log.logIndex}_${i}`,
              userAddress: userAddress.toLowerCase(),
              positionId: tokenId.toString(),
              marketId: marketId.toString(),
              outcome: outcome,
              txType: txType,
              amount: amount.toString(),
              price: null,
              amountInUsdc: null,
              txHash: log.transactionHash,
              blockNumber: BigInt(blockNumber),
              timestamp: new Date(timestamp * 1000),
            });

            transactions.push(userTx);
          }
        }

      } catch (err: any) {
        console.error(`[BACKFILL] Error parsing log:`, err.message);
        continue;
      }
    }

    return transactions;
  }

  /**
   * Get block timestamp from RPC
   */
  private async getBlockTimestamp(blockNumber: number): Promise<number> {
    const response = await fetch(this.rpcUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'eth_getBlockByNumber',
        params: [`0x${blockNumber.toString(16)}`, false]
      })
    });

    const data = await response.json();
    if (data.error) {
      throw new Error(`RPC error getting block: ${data.error.message}`);
    }

    return parseInt(data.result.timestamp, 16);
  }
}

/**
 * Create backfill service instance
 */
export function createBackfillService(): BackfillService {
  const rpcUrl = process.env.RPC_POLYGON_HTTP || process.env.POLYGON_RPC_URL || 'https://polygon-rpc.com';

  return new BackfillService({
    rpcUrl,
    lookbackHours: 2 // Look back 2 hours for new addresses
  });
}
