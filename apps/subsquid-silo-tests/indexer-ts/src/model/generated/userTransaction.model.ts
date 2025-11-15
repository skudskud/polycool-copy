import {BigDecimal} from "@subsquid/big-decimal"
import {Entity as Entity_, Column as Column_, PrimaryColumn as PrimaryColumn_, StringColumn as StringColumn_, Index as Index_, IntColumn as IntColumn_, BigDecimalColumn as BigDecimalColumn_, BigIntColumn as BigIntColumn_, DateTimeColumn as DateTimeColumn_} from "@subsquid/typeorm-store"

@Entity_({name: 'trades'})
export class Trade {
    constructor(props?: Partial<Trade>) {
        Object.assign(this, props)
    }

    @PrimaryColumn_()
    id!: number

    @IntColumn_({nullable: false})
    watchedAddressId!: number

    @StringColumn_({nullable: false})
    marketId!: string

    @StringColumn_({nullable: false})
    outcome!: string

    @BigDecimalColumn_({nullable: false})
    amount!: BigDecimal

    @BigDecimalColumn_({nullable: false})
    price!: BigDecimal

    @StringColumn_({nullable: false, unique: true})
    txHash!: string

    @IntColumn_({nullable: true})
    blockNumber!: number | undefined | null

    @DateTimeColumn_({nullable: false})
    timestamp!: Date

    @StringColumn_({nullable: false})
    tradeType!: string

    @IntColumn_({nullable: true})
    isProcessed!: boolean | undefined | null

    @DateTimeColumn_({nullable: true})
    createdAt!: Date | undefined | null
}

// Legacy class for webhook compatibility (not stored in DB)
export class UserTransaction {
    id!: string;
    txId!: string;
    userAddress!: string;
    positionId?: string | null;
    marketId?: string | null;
    outcome?: number | null;
    txType!: string;
    amount!: string;
    price?: BigDecimal | null;
    amountInUsdc?: BigDecimal | null;
    txHash!: string;
    blockNumber!: bigint;
    timestamp!: Date;

    constructor(props: Partial<UserTransaction>) {
        Object.assign(this, props);
    }
}
