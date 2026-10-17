"""
laya_mlx_engine.py — motor de señales BTC 5m para Polymarket (Apple Silicon / MLX).

Piezas (todas locales, sin PyTorch):
  1. GAN condicional (MLX): genera trayectorias de 5 retornos de 1 min dado el contexto
     reciente. De ahí sale P(UP) por Monte Carlo, condicionada al precio actual vs. el
     "price to beat" (strike) de la vela de 5 min en curso.
  2. Agente Q (MLX): decide WAIT / BUY_UP / BUY_DOWN comparando P(UP) del modelo contra
     los precios (asks) de Polymarket. Episodio de un solo paso => gamma = 0.
  3. Kelly fraccional para contratos binarios.
  4. LayaGate (opcional): usa `laya-mlx` como compuerta de veto zero-shot. NO es un
     predictor de precios; solo puede bajar BUY -> WAIT, nunca subir WAIT -> BUY.

IMPORTANTE: laya-mlx es un runtime de decisiones tipadas (choice/score/noul) basado en un
encoder bidireccional. No contiene GAN ni RL; por eso esas piezas viven aquí, en MLX puro.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

L = 30          # minutos de contexto (retornos de 1 min)
H = 5           # horizonte: 5 min
ZD = 16         # dimensión del ruido
SD = 7          # dimensión del estado del agente Q
ACTIONS = ["WAIT", "BUY_UP", "BUY_DOWN"]
MODELS = Path(__file__).parent / "models"

RISK = {  # perfiles: fracción de Kelly, tope de stake (% bankroll), edge mínimo (prob.)
    "conservative": dict(kelly=0.10, cap=0.02, min_edge=0.06),
    "balanced": dict(kelly=0.25, cap=0.05, min_edge=0.04),
    "aggressive": dict(kelly=0.50, cap=0.10, min_edge=0.03),
}


# --------------------------------------------------------------------------- datos
def synthetic_closes(n: int = 9000, seed: int = 7) -> np.ndarray:
    """Random walk con volatilidad variable. Solo para pruebas sin red."""
    rng = np.random.default_rng(seed)
    vol = 4e-4 * np.exp(0.5 * np.cumsum(rng.normal(0, 0.05, n)).clip(-1, 1))
    return 60000 * np.exp(np.cumsum(rng.standard_t(5, n) * vol))


def fetch_bars(period: str = "7d"):
    """Barras de 1 min de BTC-USD (Yahoo limita 1m a ~7 días). Devuelve DataFrame."""
    import yfinance as yf

    df = yf.Ticker("BTC-USD").history(period=period, interval="1m")
    if df.empty:
        raise RuntimeError("yfinance no devolvió barras de 1m para BTC-USD")
    return df


def build_dataset(closes: np.ndarray):
    """Contexto z-score (L retornos) y futuro (H retornos) en unidades de sigma."""
    r = np.diff(np.log(closes))
    idx = np.arange(L, len(r) - H)
    ctx = np.stack([r[i - L:i] for i in idx])
    fut = np.stack([r[i:i + H] for i in idx])
    sig = ctx.std(1, keepdims=True).clip(1e-5)
    return (ctx / sig).astype(np.float32), (fut / sig).astype(np.float32), sig[:, 0], idx


# --------------------------------------------------------------------------- GAN
class Generator(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(ZD + L, 128), nn.LeakyReLU(0.2),
            nn.Linear(128, 128), nn.LeakyReLU(0.2),
            nn.Linear(128, H),
        )

    def __call__(self, z, c):
        return self.net(mx.concatenate([z, c], axis=-1))


class Discriminator(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(H + L, 128), nn.LeakyReLU(0.2),
            nn.Linear(128, 64), nn.LeakyReLU(0.2),
            nn.Linear(64, 1),
        )

    def __call__(self, c, x):
        return self.net(mx.concatenate([c, x], axis=-1))


def _bce(logits, target):
    return mx.mean(nn.losses.binary_cross_entropy(logits, target, with_logits=True))


def _d_loss(D, G, c, real, z):
    fake = mx.stop_gradient(G(z, c))
    ones, zeros = mx.full((c.shape[0], 1), 0.9), mx.zeros((c.shape[0], 1))  # label smoothing
    return _bce(D(c, real), ones) + _bce(D(c, fake), zeros)


def _g_loss(G, D, c, z):
    return _bce(D(c, G(z, c)), mx.ones((c.shape[0], 1)))


def train_gan(ctx, fut, steps: int = 2500, batch: int = 256, log=print):
    G, D = Generator(), Discriminator()
    mx.eval(G.parameters(), D.parameters())
    og, od = optim.Adam(2e-4, betas=[0.5, 0.999]), optim.Adam(2e-4, betas=[0.5, 0.999])
    gd = nn.value_and_grad(D, _d_loss)
    gg = nn.value_and_grad(G, _g_loss)
    X, Y = mx.array(ctx), mx.array(fut)
    n = ctx.shape[0]
    for s in range(1, steps + 1):
        i = mx.array(np.random.randint(0, n, batch))
        c, real = X[i], Y[i]
        z = mx.random.normal((batch, ZD))
        ld, g = gd(D, G, c, real, z)
        od.update(D, g)
        lg, g = gg(G, D, c, mx.random.normal((batch, ZD)))
        og.update(G, g)
        mx.eval(G.parameters(), D.parameters(), og.state, od.state)
        if s % 500 == 0:
            log(f"  GAN {s}/{steps}  loss_D={ld.item():.3f}  loss_G={lg.item():.3f}")
    return G


def p_up(G, ctx_z, k, strike_z, n: int = 128):
    """P(precio_final >= strike). ctx_z [B,L]; k [B] minutos restantes (1..5);
    strike_z [B] = log(strike/spot)/sigma. Devuelve array numpy [B]."""
    B = ctx_z.shape[0]
    z = mx.random.normal((B, n, ZD))
    c = mx.broadcast_to(mx.array(ctx_z)[:, None, :], (B, n, L))
    cum = mx.cumsum(G(z, c), axis=-1)                                   # [B,n,H]
    ki = mx.broadcast_to(mx.array(k - 1, dtype=mx.int32)[:, None, None], (B, n, 1))
    end = mx.take_along_axis(cum, ki, axis=-1)[..., 0]                  # [B,n]
    p = mx.mean((end >= mx.array(strike_z, dtype=mx.float32)[:, None]).astype(mx.float32), axis=1)
    mx.eval(p)
    return np.array(p)


# --------------------------------------------------------------------------- mercado simulado
def _phi(x):
    return 0.5 * (1 + np.vectorize(math.erf)(x / math.sqrt(2)))


def market_proxy(strike_z, k, rng, noise=0.03, half_spread=0.01):
    """Mercado simulado: P implícita ~ Phi(distancia al strike / sqrt(k)) + ruido.
    Solo se usa para ENTRENAR/EVALUAR el agente sin histórico de órdenes de Polymarket."""
    p = _phi(-strike_z / np.sqrt(k)) + rng.normal(0, noise, len(k))
    p = p.clip(0.03, 0.97)
    return (p + half_spread).clip(0.02, 0.98), (1 - p + half_spread).clip(0.02, 0.98)


def state_vec(p, ask_up, ask_dn, k, strike_z):
    return np.stack([p, ask_up, ask_dn, p - ask_up, (1 - p) - ask_dn, k / H,
                     np.clip(strike_z, -3, 3) / 3], axis=1).astype(np.float32)


def build_env(G, closes, rng, n_samples=6000, lo=0.0, hi=1.0, gan_draws=96):
    """Muestras (estado, recompensas por acción) sobre el tramo [lo,hi] de la serie."""
    ctx, _, sig, idx = build_dataset(closes)
    a, b = int(lo * len(idx)), int(hi * len(idx))
    sel = rng.integers(a, max(b - 1, a + 1), n_samples)
    sel = sel[idx[sel] > 5]
    d, m = idx[sel], rng.integers(1, H, len(sel))       # m = minutos transcurridos (1..4)
    k = (H - m).astype(np.int64)
    s0 = d - m                                           # índice de la vela de apertura
    ok = (s0 + H) < len(closes)
    sel, d, k, s0, m = sel[ok], d[ok], k[ok], s0[ok], m[ok]
    strike_z = np.log(closes[s0] / closes[d]) / sig[sel]
    up = (closes[s0 + H] >= closes[s0]).astype(np.float32)
    pg = p_up(G, ctx[sel], k, strike_z, n=gan_draws)
    au, ad = market_proxy(strike_z, k, rng)
    S = state_vec(pg, au, ad, k, strike_z)
    R = np.stack([np.zeros_like(up), up - au, (1 - up) - ad], axis=1).astype(np.float32)
    return S, R, up, pg


# --------------------------------------------------------------------------- agente Q
class QNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(SD, 64), nn.ReLU(), nn.Linear(64, 64),
                                 nn.ReLU(), nn.Linear(64, 3))

    def __call__(self, s):
        return self.net(s)


def _q_loss(Q, s, a, r):
    q = mx.take_along_axis(Q(s), a[:, None], axis=1)[:, 0]
    return mx.mean((q - r) ** 2)          # gamma = 0: el objetivo es la recompensa inmediata


def train_q(S, R, steps=4000, batch=256, eps0=1.0, eps1=0.05, log=print):
    Q = QNet()
    mx.eval(Q.parameters())
    opt = optim.Adam(1e-3)
    lg = nn.value_and_grad(Q, _q_loss)
    n = len(S)
    for t in range(steps):
        i = np.random.randint(0, n, batch)
        eps = eps0 + (eps1 - eps0) * min(1, t / (0.6 * steps))
        greedy = np.array(mx.argmax(Q(mx.array(S[i])), axis=1))
        a = np.where(np.random.rand(batch) < eps, np.random.randint(0, 3, batch), greedy)
        r = R[i, a]
        loss, g = lg(Q, mx.array(S[i]), mx.array(a, dtype=mx.int32), mx.array(r))
        opt.update(Q, g)
        mx.eval(Q.parameters(), opt.state)
        if (t + 1) % 1000 == 0:
            log(f"  Q {t + 1}/{steps}  loss={loss.item():.4f}")
    return Q


def q_values(Q, s):
    out = Q(mx.array(s))
    mx.eval(out)
    return np.array(out)


# --------------------------------------------------------------------------- Kelly / EV
def kelly_binary(p: float, ask: float, frac: float, cap: float) -> float:
    """Fracción del bankroll al comprar una acción a `ask` que paga 1 con prob. p."""
    if not (0 < ask < 1) or p <= ask:
        return 0.0
    return float(min(cap, frac * (p - ask) / (1 - ask)))


Q_MIN = 0.02  # el valor Q de la acción debe superar este margen (frena el sobre-trading por ruido)


def choose_actions(qv, edge_up, edge_dn, min_edge):
    """Regla de doble llave (vectorizada): el agente propone, el edge mínimo confirma."""
    a = qv.argmax(1)
    a = np.where((a > 0) & (qv.max(1) < Q_MIN), 0, a)
    a = np.where((a == 1) & (edge_up < min_edge), 0, a)
    a = np.where((a == 2) & (edge_dn < min_edge), 0, a)
    return a


def evaluate(G, Q, closes, rng, fee=0.0, risk="balanced", log=print):
    """Evaluación en el 25% final de la serie (fuera de muestra). Mercado SIMULADO."""
    S, R, up, pg = build_env(G, closes, rng, n_samples=4000, lo=0.75, hi=1.0)
    brier = lambda p: float(np.mean((p - up) ** 2))
    p_mkt = (S[:, 1] + 1 - S[:, 2]) / 2      # prob. implícita del mercado simulado (sin spread)
    qa = choose_actions(q_values(Q, S), S[:, 3] - fee, S[:, 4] - fee, RISK[risk]["min_edge"])
    pnl = R[np.arange(len(S)), qa] - fee * (qa > 0)
    trades = int((qa > 0).sum())
    rep = dict(
        n=len(S), brier_gan=round(brier(pg), 4), brier_mercado_sim=round(brier(p_mkt), 4),
        brier_const=round(brier(np.full_like(up, up.mean())), 4),
        trades=trades, share_trades=round(trades / len(S), 3),
        mean_pnl_per_share=round(float(pnl[qa > 0].mean()) if trades else 0.0, 4),
    )
    log("  Evaluación fuera de muestra (mercado simulado): " + json.dumps(rep))
    return rep


def save_models(G, Q, meta: dict):
    MODELS.mkdir(exist_ok=True)
    G.save_weights(str(MODELS / "gan_g.safetensors"))
    Q.save_weights(str(MODELS / "qnet.safetensors"))
    (MODELS / "meta.json").write_text(json.dumps(meta, indent=2))


def load_models():
    G, Q = Generator(), QNet()
    G.load_weights(str(MODELS / "gan_g.safetensors"))
    Q.load_weights(str(MODELS / "qnet.safetensors"))
    mx.eval(G.parameters(), Q.parameters())
    return G, Q


def train_all(closes, gan_steps=2500, q_steps=4000, log=print):
    rng = np.random.default_rng(0)
    cut = int(len(closes) * 0.75)                        # split temporal: nunca entrenar con el futuro
    ctx, fut, _, _ = build_dataset(closes[:cut])
    log(f"Entrenando GAN con {len(ctx)} muestras…")
    G = train_gan(ctx, fut, steps=gan_steps, log=log)
    log("Construyendo entorno simulado y entrenando agente Q…")
    S, R, _, _ = build_env(G, closes[:cut], rng)
    Q = train_q(S, R, steps=q_steps, log=log)
    rep = evaluate(G, Q, closes, rng, log=log)
    save_models(G, Q, dict(trained_at=time.time(), bars=len(closes), eval=rep))
    return G, Q, rep


# --------------------------------------------------------------------------- Laya (opcional)
class LayaGate:
    """Veto zero-shot con laya-mlx. Si el modelo no se puede cargar, deja pasar la señal."""

    def __init__(self, repo: str = "aac6fef/laya-mlx"):
        import laya_mlx as laya

        self.agent = laya.load(repo)  # primera vez descarga el checkpoint

    def check(self, side: str, feats: dict, veto_below: float = 0.35):
        q = {"supports": {
            "type": "noul",
            "instructions": f"Do the indicators in `market` support buying the {side} outcome "
                            f"of a 5-minute Bitcoin up/down market?"}}
        res = self.agent.predict({"market": feats}, q)
        p_true = float(res["answers"]["supports"]["noul"])
        return p_true, p_true < veto_below


# --------------------------------------------------------------------------- decisión
@dataclass
class Decision:
    action: str
    side: str | None
    p_up: float
    p_down: float
    ask_up: float
    ask_down: float
    edge_up: float
    edge_down: float
    q: list
    kelly_fraction: float
    stake: float
    shares: float
    roi_if_win: float
    ev_per_share: float
    laya_p: float | None = None
    laya_veto: bool = False


def decide(Q, p, ask_up, ask_dn, k, strike_z, risk: str, bankroll: float,
           fee: float = 0.0, gate: LayaGate | None = None, feats: dict | None = None) -> Decision:
    cfg = RISK[risk]
    qv = q_values(Q, state_vec(np.array([p]), np.array([ask_up]), np.array([ask_dn]),
                               np.array([k]), np.array([strike_z])))[0]
    eu, ed = p - ask_up - fee, (1 - p) - ask_dn - fee
    a = int(choose_actions(qv[None, :], np.array([eu]), np.array([ed]), cfg["min_edge"])[0])
    side = {1: "UP", 2: "DOWN"}.get(a)
    laya_p, veto = None, False
    if side and gate is not None and feats is not None:
        try:
            laya_p, veto = gate.check(side, feats)
        except Exception:  # noqa: BLE001 - el gate nunca debe tumbar el motor
            laya_p, veto = None, False
        if veto:
            a, side = 0, None
    ask = ask_up if side == "UP" else ask_dn
    pw = p if side == "UP" else 1 - p
    f = kelly_binary(pw, ask + fee, cfg["kelly"], cfg["cap"]) if side else 0.0
    stake = f * bankroll
    return Decision(
        action=ACTIONS[a], side=side, p_up=p, p_down=1 - p, ask_up=ask_up, ask_down=ask_dn,
        edge_up=eu, edge_down=ed, q=[float(x) for x in qv], kelly_fraction=f, stake=stake,
        shares=stake / ask if side else 0.0, roi_if_win=((1 - ask) / ask) if side else 0.0,
        ev_per_share=(pw - ask - fee) if side else 0.0, laya_p=laya_p, laya_veto=veto)


# --------------------------------------------------------------------------- CLI
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train"])
    ap.add_argument("--period", default="7d")
    ap.add_argument("--synthetic", action="store_true", help="datos sintéticos (sin red)")
    ap.add_argument("--gan-steps", type=int, default=2500)
    ap.add_argument("--q-steps", type=int, default=4000)
    a = ap.parse_args()
    closes = synthetic_closes() if (a.synthetic or os.getenv("LAYA_SYNTHETIC")) \
        else fetch_bars(a.period)["Close"].to_numpy(dtype=np.float64)
    train_all(closes, a.gan_steps, a.q_steps)
