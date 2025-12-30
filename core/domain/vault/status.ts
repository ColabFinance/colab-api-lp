export type VaultStatus = {
  vault: string;

  owner: string;
  executor: string;
  adapter: string;
  dex_router: string;
  fee_collector: string;
  strategy_id: number;

  pool: string;
  nfpm: string;
  gauge: string;

  token0: { address: string; symbol: string; decimals: number };
  token1: { address: string; symbol: string; decimals: number };

  position_token_id: number;
  liquidity: number;
  lower_tick: number;
  upper_tick: number;
  tick_spacing: number;

  tick: number;
  sqrt_price_x96: number;
  prices: {
    current: { tick: number; p_t1_t0: number; p_t0_t1: number };
    lower: { tick: number; p_t1_t0: number; p_t0_t1: number };
    upper: { tick: number; p_t1_t0: number; p_t0_t1: number };
  };

  out_of_range: boolean;
  range_side: "inside" | "below" | "above";

  holdings: {
    vault_idle: { token0: number; token1: number };
    in_position: { token0: number; token1: number };
    totals: { token0: number; token1: number };
  };

  fees_uncollected: { token0: number; token1: number };

  last_rebalance_ts: number;
};
