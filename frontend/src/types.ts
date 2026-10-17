export type Side = "UP" | "DOWN";
export type Risk = "conservative" | "balanced" | "aggressive";
export type Level = [price: number, size: number];

export interface Book {
  ask: number | null;
  bid: number | null;
  asks: Level[];
  bids: Level[];
}

export interface Signal {
  action: "WAIT" | "BUY_UP" | "BUY_DOWN";
  side: Side | null;
  p_up: number;
  p_down: number;
  ask_up: number;
  ask_down: number;
  edge_up: number;
  edge_down: number;
  q: number[];
  kelly_fraction: number;
  stake: number;
  shares: number;
  roi_if_win: number;
  ev_per_share: number;
  laya_p: number | null;
  laya_veto: boolean;
  implied_yield_up: number;
  implied_yield_down: number;
}

export interface Trade {
  id: number;
  window_start: number;
  side: Side;
  entry: number;
  stake: number;
  shares: number;
  p_model: number;
  strike: number;
  status: "open" | "closed";
  final?: number;
  up?: boolean;
  win?: boolean;
  pnl?: number;
}

export interface Metrics {
  n: number;
  win_rate: number | null;
  pnl: number;
  sharpe: number | null;
  avg_roi: number | null;
}

export interface Config {
  bankroll: number;
  risk: Risk;
  fee: number;
  use_laya: boolean;
}

export interface Tick {
  type: "tick";
  ts: number;
  window: { start: number; end: number; secs_left: number; k: number };
  price: {
    spot: number;
    strike: number;
    strike_approx: boolean;
    distance_pct: number;
    sigma_1m_pct: number;
    source: string;
  };
  market: { source: "polymarket" | "simulated"; slug: string | null; up: Book; down: Book };
  signal: Signal;
  config: Config;
  risk_profiles: Record<Risk, { kelly: number; cap: number; min_edge: number }>;
  metrics: Metrics;
  open_trade: Trade | null;
  trades: Trade[];
  laya: { enabled: boolean; loaded: boolean; error: string | null };
  model: { eval?: Record<string, number> };
}

export interface Status {
  type: "status";
  phase: string;
  message: string;
}

export type Snapshot = Tick | Status;
