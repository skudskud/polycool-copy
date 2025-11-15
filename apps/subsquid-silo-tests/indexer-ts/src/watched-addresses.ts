/**
 * Watched Addresses Manager
 *
 * Fetches and caches the list of addresses to watch from the bot API
 * Used to filter transactions at source (before DB write)
 *
 * Architecture:
 * - Bot maintains external_leaders + smart_wallets tables
 * - Indexer fetches list via /subsquid/watched_addresses
 * - Refreshes every 5 minutes (configurable)
 * - O(1) lookup via Set<string>
 */

import axios from 'axios';
// import { createBackfillService } from './backfill-service'; // DISABLED: Too expensive for free tier

interface WatchedAddress {
  address: string;
  type: 'external_leader' | 'smart_wallet';
  user_id: number | null;
}

interface WatchedAddressesResponse {
  addresses: WatchedAddress[];
  total: number;
  timestamp: string;
}

class WatchedAddressManager {
  private watchedAddresses: Set<string> = new Set();
  private lastRefresh: number = 0;
  private readonly REFRESH_INTERVAL_MS: number;
  private readonly botApiUrl: string;
  private readonly enabled: boolean;
  // private backfillService: ReturnType<typeof createBackfillService> | null = null; // DISABLED

  constructor(botApiUrl: string | undefined, refreshIntervalMinutes: number = 5) {
    this.botApiUrl = botApiUrl || '';
    this.REFRESH_INTERVAL_MS = refreshIntervalMinutes * 60 * 1000;
    this.enabled = !!botApiUrl;

    // DISABLE BACKFILL: Too expensive for free tier RPC
    // this.backfillService = createBackfillService();

    if (!this.enabled) {
      console.log('[WATCHED] ⚠️  BOT_API_URL not configured - will index ALL transactions');
    }
  }

  /**
   * Initialize - fetch addresses on startup
   */
  async init(db?: any): Promise<void> {
    if (!this.enabled) {
      console.log('[WATCHED] ⏭️  Filtering disabled - no BOT_API_URL');
      return;
    }

    // DISABLE BACKFILL: Too expensive for free tier RPC
    // Initialize backfill service if DB context provided
    /*
    if (db) {
      this.backfillService = createBackfillService();
    }
    */

    await this.refresh(db);
    console.log(`[WATCHED] ✅ Loaded ${this.watchedAddresses.size} addresses to watch`);
  }

  /**
   * Refresh the list of watched addresses from bot API
   * Now includes backfill for newly detected addresses
   */
  async refresh(db?: any): Promise<void> {
    if (!this.enabled) {
      return;
    }

    const now = Date.now();

    // Skip if refreshed recently (unless cache is empty - then retry immediately)
    if (now - this.lastRefresh < this.REFRESH_INTERVAL_MS && this.watchedAddresses.size > 0) {
      return;
    }

    try {
      const url = `${this.botApiUrl}/api/v1/subsquid/watched_addresses`;

      console.log(`[WATCHED] 🔄 Refreshing from ${url}...`);

      const response = await axios.get<WatchedAddressesResponse>(url, {
        timeout: 30000,  // 30 seconds (increased from 10s during high load)
        headers: {
          'User-Agent': 'Subsquid-Indexer/1.0'
        }
      });

      // Detect new addresses before clearing the set
      const oldAddresses = new Set(this.watchedAddresses);
      const newAddresses: WatchedAddress[] = [];

      // Clear and rebuild set
      this.watchedAddresses.clear();

      for (const addr of response.data.addresses) {
        const addressLower = addr.address.toLowerCase();
        this.watchedAddresses.add(addressLower);

        // Check if this is a new address
        if (!oldAddresses.has(addressLower)) {
          newAddresses.push(addr);
        }
      }

      this.lastRefresh = now;

      const leaders = response.data.addresses.filter(a => a.type === 'external_leader').length;
      const smartWallets = response.data.addresses.filter(a => a.type === 'smart_wallet').length;

      console.log(
        `[WATCHED] ✅ Refreshed: ${this.watchedAddresses.size} addresses ` +
        `(${leaders} leaders, ${smartWallets} smart wallets)`
      );

      // DISABLE BACKFILL: Too expensive for free tier RPC
      // Backfill historical transactions for new addresses
      /*
      if (newAddresses.length > 0 && this.backfillService && db) {
        console.log(`[WATCHED] 🔄 Backfilling ${newAddresses.length} new addresses...`);

        // Get current block for backfill range calculation
        const currentBlock = await this.getCurrentBlockNumber();

        for (const newAddr of newAddresses) {
          try {
            const backfilledCount = await this.backfillService.backfillAddress(
              newAddr.address,
              currentBlock,
              db
            );

            if (backfilledCount > 0) {
              console.log(`[WATCHED] ✅ Backfilled ${backfilledCount} historical tx for ${newAddr.address.slice(0, 10)}...`);
            }
          } catch (err: any) {
            console.error(`[WATCHED] ❌ Backfill failed for ${newAddr.address.slice(0, 10)}...: ${err.message}`);
          }
        }
      }
      */

    } catch (err: any) {
      console.error(
        `[WATCHED] ❌ Failed to refresh addresses: ${err.message}`,
        `(cache: ${this.watchedAddresses.size} addresses, will retry in ${this.REFRESH_INTERVAL_MS / 1000}s)`
      );

      // If cache is empty, we're in trouble - log a warning
      if (this.watchedAddresses.size === 0) {
        console.warn(
          `[WATCHED] ⚠️  WARNING: Cache is empty! Indexing ALL transactions as fallback.`,
          `This will cause high load. Check bot health: ${this.botApiUrl}/health`
        );
      }

      // Keep existing cache if refresh fails
      // This prevents indexer from crashing if bot is temporarily down
    }
  }

  /**
   * Check if an address should be watched
   * O(1) lookup via Set
   *
   * @param address - Ethereum address to check
   * @returns true if address should be indexed
   */
  isWatched(address: string): boolean {
    // If filtering disabled, watch everything
    if (!this.enabled) {
      return true;
    }

    // If cache is empty (e.g., bot unreachable), watch everything
    // This prevents data loss if bot is temporarily down
    if (this.watchedAddresses.size === 0) {
      return true;
    }

    return this.watchedAddresses.has(address.toLowerCase());
  }

  /**
   * Get current watch count
   */
  getWatchCount(): number {
    return this.watchedAddresses.size;
  }

  /**
   * Check if filtering is enabled
   */
  isEnabled(): boolean {
    return this.enabled;
  }

  /**
   * Get current block number from RPC
   */
  private async getCurrentBlockNumber(): Promise<number> {
    try {
      const rpcUrl = process.env.RPC_POLYGON_HTTP || process.env.POLYGON_RPC_URL || 'https://polygon-rpc.com';

      const response = await axios.post(rpcUrl, {
        jsonrpc: '2.0',
        id: 1,
        method: 'eth_blockNumber',
        params: []
      }, {
        timeout: 10000,
        headers: {
          'Content-Type': 'application/json'
        }
      });

      const blockHex = response.data.result;
      return parseInt(blockHex, 16);
    } catch (err: any) {
      console.error(`[WATCHED] ❌ Failed to get current block: ${err.message}`);
      // Fallback to a recent block estimate
      return 78300000; // Approximate current block as fallback
    }
  }

  /**
   * Get stats for logging
   */
  getStats(): { enabled: boolean; count: number; lastRefresh: Date | null } {
    return {
      enabled: this.enabled,
      count: this.watchedAddresses.size,
      lastRefresh: this.lastRefresh > 0 ? new Date(this.lastRefresh) : null
    };
  }
}

// Singleton instance
export const watchedAddressManager = new WatchedAddressManager(
  process.env.BOT_API_URL,
  1 // Refresh every 1 minute (reduced from 5 for faster detection)
);
