import * as p from '@subsquid/evm-codec'
import {fun, ContractBase, type AbiFunction, type FunctionReturn, type FunctionArguments} from '@subsquid/evm-abi'

const aggregate = fun('0x252dba42', "aggregate((address,bytes)[]", {
  calls: p.array(p.struct({
    target: p.address,
    callData: p.bytes
  }))
}, {blockNumber: p.uint256, returnData: p.array(p.bytes)})

const tryAggregate = fun('0xbce38bd7', "tryAggregate(bool,(address,bytes)[])", {
  requireSuccess: p.bool,
  calls: p.array(p.struct({target: p.address, callData: p.bytes}))
}, p.array(p.struct({success: p.bool, returnData: p.bytes})))

export type MulticallResult<T extends AbiFunction<any, any>> = {
  success: true
  value: FunctionReturn<T>
} | {
  success: false
  returnData?: string
  value?: undefined
}

type AnyFunc = AbiFunction<any, any>
type AggregateTuple<T extends AnyFunc = AnyFunc> = [func: T, address: string, args: T extends AnyFunc ? FunctionArguments<T> : never]
type Call = {target: string, callData: string}

export class Multicall extends ContractBase {
  static aggregate = aggregate
  static tryAggregate = tryAggregate

  aggregate<TF extends AnyFunc>(
    func: TF,
    address: string,
    calls: FunctionArguments<TF>[],
    paging?: number
  ): Promise<FunctionReturn<TF>[]>

  aggregate<TF extends AnyFunc>(
    func: TF,
    calls: (readonly [address: string, args: FunctionArguments<TF>])[],
    paging?: number
  ): Promise<FunctionReturn<TF>[]>

  aggregate(
    calls: AggregateTuple[],
    paging?: number
  ): Promise<any[]>

  async aggregate(...args: any[]): Promise<any[]> {
    let [calls, funcs, page] = this.makeCalls(args)
    let size = calls.length
    let results = new Array(size)
    for (let [from, to] of splitIntoPages(size, page)) {
      let {returnData} = await this.eth_call(aggregate, {calls: calls.slice(from, to)})
      for (let i = from; i < to; i++) {
        let data = returnData[i - from]
        results[i] = funcs[i].decodeResult(data)
      }
    }
    return results
  }

  tryAggregate<TF extends AnyFunc>(
    func: TF,
    address: string,
    calls: FunctionArguments<TF>[],
    paging?: number
  ): Promise<MulticallResult<TF>[]>

  tryAggregate<TF extends AnyFunc>(
    func: TF,
    calls: (readonly [address: string, args: FunctionArguments<TF>])[],
    paging?: number
  ): Promise<MulticallResult<TF>[]>

  tryAggregate(
    calls: AggregateTuple[],
    paging?: number
  ): Promise<MulticallResult<any>[]>

  async tryAggregate(...args: any[]): Promise<any[]> {
    let [calls, funcs, page] = this.makeCalls(args)
    let size = calls.length
    let results = new Array(size)
    for (let [from, to] of splitIntoPages(size, page)) {
      let response = await this.eth_call(tryAggregate, {
        requireSuccess: false,
        calls: calls.slice(from, to)
      })
      for (let i = from; i < to; i++) {
        let res = response[i - from]
        if (res.success) {
          try {
            results[i] = {
              success: true,
              value: funcs[i].decodeResult(res.returnData)
            }
          } catch (err: any) {
            results[i] = {success: false, returnData: res.returnData}
          }
        } else {
          results[i] = {success: false}
        }
      }
    }
    return results
  }

  private makeCalls(args: any[]): [calls: Call[], funcs: AnyFunc[], page: number] {
    let page = typeof args[args.length - 1] == 'number' ? args.pop()! : Number.MAX_SAFE_INTEGER
    switch (args.length) {
      case 1: {
        let list: AggregateTuple[] = args[0]
        let calls: Call[] = new Array(list.length)
        let funcs = new Array(list.length)
        for (let i = 0; i < list.length; i++) {
          let [func, address, args] = list[i]
          calls[i] = {target: address, callData: func.encode(args)}
          funcs[i] = func
        }
        return [calls, funcs, page]
      }
      case 2: {
        let func: AnyFunc = args[0]
        let list: [address: string, args: any][] = args[1]
        let calls: Call[] = new Array(list.length)
        let funcs = new Array(list.length)
        for (let i = 0; i < list.length; i++) {
          let [address, args] = list[i]
          calls[i] = {target: address, callData: func.encode(args)}
          funcs[i] = func
        }
        return [calls, funcs, page]
      }
      case 3: {
        let func: AnyFunc = args[0]
        let address: string = args[1]
        let list: any = args[2]
        let calls: Call[] = new Array(list.length)
        let funcs = new Array(list.length)
        for (let i = 0; i < list.length; i++) {
          let args = list[i]
          calls[i] = {target: address, callData: func.encode(args)}
          funcs[i] = func
        }
        return [calls, funcs, page]
      }
      default:
        throw new Error('unexpected number of arguments')
    }
  }
}


function* splitIntoPages(size: number, page: number): Iterable<[from: number, to: number]> {
  let from = 0
  while (size) {
    let step = Math.min(page, size)
    let to = from + step
    yield [from, to]
    size -= step
    from = to
  }
}

// Helper functions for parsing Conditional Tokens Transfer events

const ZERO_ADDRESS = '0x0000000000000000000000000000000000000000'

export interface ParsedTransfer {
  operator: string
  from: string
  to: string
  tokenId: bigint
  amount: bigint
}

export interface ParsedTransferBatch {
  operator: string
  from: string
  to: string
  tokenIds: bigint[]
  amounts: bigint[]
}

export function parseTransferEvent(topics: string[], data: string): ParsedTransfer | null {
  try {
    if (topics.length < 4 || data.length < 130) {
      return null
    }

    // topics[0] = event signature (already filtered)
    // topics[1] = operator (indexed)
    // topics[2] = from (indexed)
    // topics[3] = to (indexed)
    const operator = `0x${topics[1].slice(-40)}`
    const from = `0x${topics[2].slice(-40)}`
    const to = `0x${topics[3].slice(-40)}`

    // data contains: tokenId (32 bytes), amount (32 bytes)
    const tokenId = BigInt('0x' + data.slice(2, 66))
    const amount = BigInt('0x' + data.slice(66, 130))

    return { operator, from, to, tokenId, amount }
  } catch (e) {
    return null
  }
}

export function parseTransferBatchEvent(topics: string[], data: string): ParsedTransferBatch | null {
  try {
    if (topics.length < 4) {
      return null
    }

    // topics[0] = event signature (already filtered)
    // topics[1] = operator (indexed)
    // topics[2] = from (indexed)
    // topics[3] = to (indexed)
    const operator = `0x${topics[1].slice(-40)}`
    const from = `0x${topics[2].slice(-40)}`
    const to = `0x${topics[3].slice(-40)}`

    // data format for TransferBatch:
    // - offset1 (32 bytes) = offset to ids array
    // - offset2 (32 bytes) = offset to values array
    // - ids array: length (32) + elements (32 each)
    // - values array: length (32) + elements (32 each)

    // Parse ids array
    const idsOffset = parseInt(data.slice(2, 66), 16) * 2 // Convert byte offset to string offset
    const idsLength = parseInt(data.slice(idsOffset, idsOffset + 64), 16)
    const tokenIds: bigint[] = []
    
    for (let i = 0; i < idsLength; i++) {
      const tokenId = BigInt('0x' + data.slice(idsOffset + 64 + (i * 64), idsOffset + 64 + ((i + 1) * 64)))
      tokenIds.push(tokenId)
    }

    // Parse values array
    const valuesOffset = parseInt(data.slice(66, 130), 16) * 2 // Convert byte offset to string offset
    const valuesLength = parseInt(data.slice(valuesOffset, valuesOffset + 64), 16)
    const amounts: bigint[] = []
    
    for (let i = 0; i < valuesLength; i++) {
      const amount = BigInt('0x' + data.slice(valuesOffset + 64 + (i * 64), valuesOffset + 64 + ((i + 1) * 64)))
      amounts.push(amount)
    }

    // Validate that both arrays have the same length
    if (tokenIds.length !== amounts.length) {
      return null
    }

    return { operator, from, to, tokenIds, amounts }
  } catch (e) {
    return null
  }
}

export interface MarketAndOutcome {
  marketId: bigint
  outcome: number
}

export function extractMarketIdAndOutcome(tokenId: bigint): MarketAndOutcome {
  // Market ID = tokenId >> 1 (divide by 2)
  // Outcome = tokenId & 1 (0=NO, 1=YES)
  const marketId = tokenId >> 1n
  const outcome = Number(tokenId & 1n)
  return { marketId, outcome }
}

export function determineTransactionType(from: string, to: string): 'BUY' | 'SELL' | null {
  if (from.toLowerCase() === ZERO_ADDRESS) {
    return 'BUY'
  }
  if (to.toLowerCase() === ZERO_ADDRESS) {
    return null // Ignore burns
  }
  return 'SELL'
}

export function getUserAddress(txType: 'BUY' | 'SELL', from: string, to: string): string {
  return txType === 'BUY' ? to : from
}
