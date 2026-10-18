"""
server.py — adaptador FastAPI/WebSocket entre laya_mlx_engine y el dashboard React.

  GET  /api/health   estado general
  GET  /api/state    último snapshot
  GET  /api/trades   bitácora de paper trades + métricas
  POST /api/config   {bankroll, risk, fee, use_laya}
  WS   /ws           snapshot JSON cada ~1 s

Solo paper trading: no hay ejecución de órdenes reales.
Variables de entorno: LAYA_SYNTHETIC=1 (datos simulados, sin red).
La compuerta Laya se activa automáticamente en cada arranque.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import httpx
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import laya_mlx_engine as eng

SYN = bool(os.getenv("LAYA_SYNTHETIC"))
WIN = 300
TRADES_FILE = Path(__file__).parent / "trades.jsonl"
# MLX trabaja con streams por hilo: todo el cómputo MLX corre en UN solo hilo dedicado.
MLX = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")


# --------------------------------------------------------------------------- precio
class Feed:
    """Barras de 1 min + precio spot. yfinance (real) o random walk (LAYA_SYNTHETIC=1)."""

    def __init__(self):
        self.data = (np.array([]), np.array([]), np.array([]))  # ts, opens, closes
        self.spot: float | None = None

    def refresh(self, period: str = "2d"):
        if SYN:
            if self.spot is None:
                c = eng.synthetic_closes(3000)
                now = int(time.time() // 60 * 60)
                self.data = (now - 60 * np.arange(len(c))[::-1], c.copy(), c)
                self.spot = float(c[-1])
            return
        df = eng.fetch_bars(period)
        ts = np.array([int(t.timestamp()) for t in df.index])
        self.data = (ts, df["Open"].to_numpy(float), df["Close"].to_numpy(float))
        self.spot = float(self.data[2][-1])

    def step_synthetic(self):
        ts, op, cl = self.data
        self.spot *= math.exp(np.random.normal(0, 4e-4 / math.sqrt(60)))
        m = int(time.time() // 60 * 60)
        if m > ts[-1]:
            self.data = (np.append(ts, m), np.append(op, self.spot), np.append(cl, self.spot))
        else:
            cl[-1] = self.spot

    def strike(self, start: int, cache: dict):
        """Precio de apertura de la vela de 5 min. Aproximado con el spot si la barra aún no llega."""
        ts, op, _ = self.data
        pos = int(np.searchsorted(ts, start))
        if pos < len(ts) and ts[pos] == start:
            cache[start] = (float(op[pos]), False)
        elif start not in cache:
            cache[start] = (float(self.spot), True)
        return cache[start]


# --------------------------------------------------------------------------- Polymarket
class PolyFeed:
    """Lee precios de Polymarket (Gamma + CLOB). Sin autenticación: solo lectura.
    Si algo falla devuelve None y el motor usa odds simuladas (marcadas como tal)."""

    GAMMA, CLOB = "https://gamma-api.polymarket.com", "https://clob.polymarket.com"

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=3.0)
        self.tokens: dict[int, dict] = {}
        self.cache: tuple[int, float, dict] | None = None

    async def _tokens(self, start: int):
        if start in self.tokens:
            return self.tokens[start]
        slug = f"btc-updown-5m-{start}"
        r = await self.http.get(f"{self.GAMMA}/markets", params={"slug": slug})
        m = r.json()[0]
        outs = json.loads(m["outcomes"]) if isinstance(m["outcomes"], str) else m["outcomes"]
        ids = json.loads(m["clobTokenIds"]) if isinstance(m["clobTokenIds"], str) else m["clobTokenIds"]
        by = {o.lower(): t for o, t in zip(outs, ids)}
        self.tokens[start] = dict(slug=slug, up=by["up"], down=by["down"])
        return self.tokens[start]

    async def _book(self, token: str):
        b = (await self.http.get(f"{self.CLOB}/book", params={"token_id": token})).json()
        asks = sorted((float(x["price"]), float(x["size"])) for x in b.get("asks", []))
        bids = sorted(((float(x["price"]), float(x["size"])) for x in b.get("bids", [])), reverse=True)
        return dict(ask=asks[0][0] if asks else None, bid=bids[0][0] if bids else None,
                    asks=asks[:3], bids=bids[:3])

    async def get(self, start: int):
        if self.cache and self.cache[0] == start and time.time() - self.cache[1] < 2:
            return self.cache[2]
        try:
            t = await self._tokens(start)
            up, dn = await asyncio.gather(self._book(t["up"]), self._book(t["down"]))
            if up["ask"] is None or dn["ask"] is None:
                return None
            out = dict(source="polymarket", slug=t["slug"], up=up, down=dn)
            self.cache = (start, time.time(), out)
            return out
        except Exception:  # noqa: BLE001
            return None


def simulated_odds(strike_z: float, k: int):
    p0 = float(eng._phi(np.array([-strike_z / math.sqrt(k)]))[0])
    au, ad = min(max(p0 + 0.01, 0.02), 0.98), min(max(1 - p0 + 0.01, 0.02), 0.98)
    mk = lambda a: dict(ask=a, bid=round(a - 0.02, 3), asks=[(a, 0.0)], bids=[])
    return dict(source="simulated", slug=None, up=mk(au), down=mk(ad))


# --------------------------------------------------------------------------- runtime
class Config(BaseModel):
    bankroll: float | None = None
    risk: str | None = None
    fee: float | None = None
    use_laya: bool | None = None


class Runtime:
    def __init__(self):
        self.feed, self.poly = Feed(), PolyFeed()
        self.G = self.Q = None
        self.phase, self.msg, self.meta = "booting", "Iniciando…", {}
        self.cfg = dict(bankroll=1000.0, risk="balanced", fee=0.0, use_laya=True)
        self.gate, self.gate_err = None, None
        self.trades: list[dict] = []
        self.open: dict | None = None
        self.cur_win: int | None = None
        self.streak, self.last_side = 0, None
        self.strikes: dict[int, tuple] = {}
        self.snapshot: dict = {"type": "status", "phase": "booting", "message": "Iniciando…"}
        self.clients: set[WebSocket] = set()
        if TRADES_FILE.exists():
            self.trades = [json.loads(x) for x in TRADES_FILE.read_text().splitlines() if x.strip()]

    # ---- arranque (hilo MLX)
    def _bootstrap(self):
        try:
            self.phase, self.msg = "data", "Descargando barras de 1 min…"
            self.feed.refresh("7d")
            closes = self.feed.data[2]
            if len(closes) < 600:
                raise RuntimeError(f"Solo {len(closes)} barras de 1m; se necesitan ≥600")
            if (eng.MODELS / "qnet.safetensors").exists():
                self.G, self.Q = eng.load_models()
                mp = eng.MODELS / "meta.json"
                self.meta = json.loads(mp.read_text()) if mp.exists() else {}
            else:
                self.phase = "training"
                log = lambda m: setattr(self, "msg", m.strip())
                self.G, self.Q, rep = eng.train_all(closes, log=log)
                self.meta = dict(trained_at=time.time(), eval=rep)
            if self.cfg["use_laya"]:
                self._load_gate()
            self.phase, self.msg = "ready", "Listo"
        except Exception as e:  # noqa: BLE001
            self.phase, self.msg = "error", f"{type(e).__name__}: {e}"

    def _load_gate(self):
        try:
            self.gate, self.gate_err = eng.LayaGate(), None
        except Exception as e:  # noqa: BLE001
            self.gate, self.gate_err = None, f"{type(e).__name__}: {e}"

    # ---- métricas y paper trading
    def metrics(self):
        t = self.trades
        if not t:
            return dict(n=0, win_rate=None, pnl=0.0, sharpe=None, avg_roi=None)
        rets = np.array([x["pnl"] / x["stake"] for x in t if x["stake"] > 0])
        sd = rets.std(ddof=1) if len(rets) > 1 else 0.0
        return dict(n=len(t), win_rate=float(np.mean([x["win"] for x in t])),
                    pnl=float(sum(x["pnl"] for x in t)),
                    sharpe=float(rets.mean() / sd) if sd > 0 else None,   # por trade, sin anualizar
                    avg_roi=float(rets.mean()))

    def _resolve(self, win_start: int, final_price: float):
        o = self.open
        if not o or o["window_start"] != win_start:
            return
        up = final_price >= o["strike"]
        win = (up and o["side"] == "UP") or ((not up) and o["side"] == "DOWN")
        pnl = (o["shares"] if win else 0.0) - o["stake"] - self.cfg["fee"] * o["stake"]
        done = {**o, "final": final_price, "up": up, "win": win, "pnl": pnl, "status": "closed"}
        self.trades.append(done)
        with TRADES_FILE.open("a") as f:
            f.write(json.dumps(done) + "\n")
        self.open = None

    # ---- inferencia (hilo MLX)
    def _p_up(self, ctx_z, k, strike_z):
        p = float(eng.p_up(self.G, ctx_z, np.array([k]), np.array([strike_z]), n=512)[0])
        return min(max(p, 0.01), 0.99)            # evita probabilidades degeneradas del Monte Carlo

    def _decide(self, p, au, ad, k, strike_z, feats):
        gate = self.gate if self.cfg["use_laya"] else None
        return eng.decide(self.Q, p, au, ad, k, strike_z, self.cfg["risk"], self.cfg["bankroll"],
                          self.cfg["fee"], gate, feats)

    # ---- un tick
    async def tick(self) -> dict:
        if self.phase != "ready":
            return {"type": "status", "phase": self.phase, "message": self.msg}
        loop = asyncio.get_running_loop()
        now = time.time()
        start = int(now // WIN * WIN)
        left = start + WIN - now
        if SYN:
            self.feed.step_synthetic()
        spot = self.feed.spot
        if self.cur_win is not None and start != self.cur_win:
            self._resolve(self.cur_win, spot)
            self.strikes.pop(self.cur_win, None)
        self.cur_win = start
        strike, approx = self.feed.strike(start, self.strikes)
        closes = self.feed.data[2]
        if len(closes) < eng.L + 1:
            return {"type": "status", "phase": "data", "message": "Pocas barras"}
        c = closes[-(eng.L + 1):].copy()
        c[-1] = spot
        r = np.diff(np.log(c))
        sigma = max(float(r.std()), 1e-5)
        ctx_z = (r / sigma)[None, :].astype(np.float32)
        k = int(np.clip(math.ceil(left / 60), 1, eng.H))
        strike_z = math.log(strike / spot) / sigma

        mkt = None if SYN else await self.poly.get(start)
        if mkt is None:
            mkt = simulated_odds(strike_z, k)
        au, ad = mkt["up"]["ask"], mkt["down"]["ask"]
        feats = dict(spot=round(spot, 1), price_to_beat=round(strike, 1),
                     distance_pct=round((spot / strike - 1) * 100, 4), minutes_left=k,
                     vol_1m_pct=round(sigma * 100, 4), ret_30m_pct=round((c[-1] / c[0] - 1) * 100, 4),
                     ask_up=round(au, 3), ask_down=round(ad, 3))

        def work():
            p = self._p_up(ctx_z, k, strike_z)
            return p, self._decide(p, au, ad, k, strike_z, feats)

        p, d = await loop.run_in_executor(MLX, work)

        # histéresis: la misma señal debe repetirse 3 ticks seguidos antes de abrir un paper trade
        self.streak = self.streak + 1 if (d.side and d.side == self.last_side) else 1
        self.last_side = d.side
        # paper trade: máx. 1 por vela, entre 20 s y 240 s antes del cierre
        if d.side and self.streak >= 3 and self.open is None and 20 <= left <= 240 and d.stake > 0:
            ask = au if d.side == "UP" else ad
            self.open = dict(id=len(self.trades) + 1, window_start=start, side=d.side, entry=ask,
                             stake=d.stake, shares=d.shares, p_model=p if d.side == "UP" else 1 - p,
                             strike=strike, opened_at=now, status="open")
        return {
            "type": "tick", "ts": now, "phase": "ready",
            "window": dict(start=start, end=start + WIN, secs_left=left, k=k),
            "price": dict(spot=spot, strike=strike, strike_approx=approx,
                          distance_pct=(spot / strike - 1) * 100, sigma_1m_pct=sigma * 100,
                          source="synthetic" if SYN else "yfinance"),
            "market": mkt,
            "signal": {**asdict(d), "implied_yield_up": (1 - au) / au, "implied_yield_down": (1 - ad) / ad},
            "config": self.cfg, "risk_profiles": eng.RISK, "metrics": self.metrics(),
            "open_trade": self.open, "trades": self.trades[-50:][::-1],
            "laya": dict(enabled=self.cfg["use_laya"], loaded=self.gate is not None, error=self.gate_err),
            "model": self.meta,
        }

    async def broadcast(self, snap: dict):
        self.snapshot = snap
        txt = json.dumps(snap, default=float)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(txt)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def refresh_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(20)
            if self.phase == "ready" and not SYN:
                try:
                    await loop.run_in_executor(None, self.feed.refresh, "2d")
                except Exception:  # noqa: BLE001  - se conserva el último dato bueno
                    pass

    async def run(self):
        asyncio.create_task(self.refresh_loop())
        asyncio.get_running_loop().run_in_executor(MLX, self._bootstrap)
        while True:
            t0 = time.time()
            try:
                snap = await self.tick()
            except Exception as e:  # noqa: BLE001
                snap = {"type": "status", "phase": "error", "message": f"{type(e).__name__}: {e}"}
            await self.broadcast(snap)
            await asyncio.sleep(max(0.0, 1.0 - (time.time() - t0)))


rt = Runtime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(rt.run())
    yield
    task.cancel()


app = FastAPI(title="LAYA BTC 5m engine", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return dict(phase=rt.phase, message=rt.msg, synthetic=SYN, laya_loaded=rt.gate is not None)


@app.get("/api/state")
def state():
    return rt.snapshot


@app.get("/api/trades")
def trades():
    return dict(trades=rt.trades[::-1], metrics=rt.metrics())


@app.post("/api/config")
async def set_config(c: Config):
    if c.bankroll is not None and c.bankroll > 0:
        rt.cfg["bankroll"] = c.bankroll
    if c.risk in eng.RISK:
        rt.cfg["risk"] = c.risk
    if c.fee is not None and 0 <= c.fee <= 0.1:
        rt.cfg["fee"] = c.fee
    if c.use_laya is not None:
        rt.cfg["use_laya"] = c.use_laya
        if c.use_laya and rt.gate is None:
            await asyncio.get_running_loop().run_in_executor(MLX, rt._load_gate)
    return rt.cfg


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    rt.clients.add(sock)
    try:
        await sock.send_text(json.dumps(rt.snapshot, default=float))
        while True:
            await sock.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        rt.clients.discard(sock)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
