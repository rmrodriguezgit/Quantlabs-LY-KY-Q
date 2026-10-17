import { useEffect, useState } from "react";
import type { Config, Risk, Tick } from "../types";
import { pct, usd } from "../format";

const RISKS: { id: Risk; label: string }[] = [
  { id: "conservative", label: "Conservador" },
  { id: "balanced", label: "Equilibrado" },
  { id: "aggressive", label: "Agresivo" },
];

export function SizingPanel({ t, onConfig }: { t: Tick; onConfig: (c: Partial<Config>) => void }) {
  const [bankroll, setBankroll] = useState(String(t.config.bankroll));
  const [fee, setFee] = useState(String(t.config.fee * 100));
  useEffect(() => setBankroll(String(t.config.bankroll)), [t.config.bankroll]);

  const s = t.signal;
  const prof = t.risk_profiles[t.config.risk];
  const commitBankroll = () => {
    const v = parseFloat(bankroll);
    if (v > 0) onConfig({ bankroll: v });
  };
  const commitFee = () => {
    const v = parseFloat(fee);
    if (v >= 0 && v <= 10) onConfig({ fee: v / 100 });
  };
  const win = s.side ? s.shares - s.stake : 0;

  return (
    <section aria-label="Tamaño de posición" className="space-y-5">
      <h2 className="text-lg font-semibold">Tamaño de posición (Kelly)</h2>

      <label className="block text-sm">
        <span className="text-muted">Bankroll (USD)</span>
        <input
          inputMode="decimal"
          value={bankroll}
          onChange={(e) => setBankroll(e.target.value)}
          onBlur={commitBankroll}
          onKeyDown={(e) => e.key === "Enter" && commitBankroll()}
          className="num mt-1 w-full border border-line bg-panel px-3 py-2 text-lg"
        />
      </label>

      <fieldset>
        <legend className="text-sm text-muted">Perfil de riesgo</legend>
        <div className="mt-1 grid grid-cols-3 border border-line">
          {RISKS.map((r) => (
            <button
              key={r.id}
              onClick={() => onConfig({ risk: r.id })}
              aria-pressed={t.config.risk === r.id}
              className={`px-2 py-2 text-sm ${t.config.risk === r.id ? "bg-ink text-paper" : "bg-panel hover:bg-line/50"}`}
            >
              {r.label}
            </button>
          ))}
        </div>
        <p className="mt-1 text-xs text-muted">
          {prof.kelly * 100}% de Kelly, tope {prof.cap * 100}% del bankroll, ventaja mínima {prof.min_edge * 100} pts.
        </p>
      </fieldset>

      <label className="block text-sm">
        <span className="text-muted">Comisión supuesta (% del monto)</span>
        <input
          inputMode="decimal"
          value={fee}
          onChange={(e) => setFee(e.target.value)}
          onBlur={commitFee}
          onKeyDown={(e) => e.key === "Enter" && commitFee()}
          className="num mt-1 w-28 border border-line bg-panel px-3 py-1"
        />
      </label>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line pt-4 text-sm">
        <div><dt className="text-muted">Lado</dt><dd className="num text-lg">{s.side ?? "—"}</dd></div>
        <div><dt className="text-muted">Fracción Kelly</dt><dd className="num text-lg">{pct(s.kelly_fraction, 2)}</dd></div>
        <div><dt className="text-muted">Monto a apostar</dt><dd className="num text-lg">{usd(s.stake)}</dd></div>
        <div><dt className="text-muted">Acciones</dt><dd className="num text-lg">{s.shares.toFixed(1)}</dd></div>
        <div><dt className="text-muted">Ganancia si acierta</dt><dd className="num text-lg">{usd(win)}</dd></div>
        <div><dt className="text-muted">Valor esperado / acción</dt><dd className="num text-lg">{s.side ? usd(s.ev_per_share, 3) : "—"}</dd></div>
      </dl>

      <label className="flex items-start gap-2 border-t border-line pt-4 text-sm">
        <input
          type="checkbox"
          checked={t.config.use_laya}
          onChange={(e) => onConfig({ use_laya: e.target.checked })}
          className="mt-1"
        />
        <span>
          Compuerta Laya (veto zero-shot)
          <span className="block text-xs text-muted">
            {t.laya.error ? `Error: ${t.laya.error}` : t.laya.loaded ? "Cargada. Solo puede cancelar una compra." : "Se descarga al activarla."}
          </span>
        </span>
      </label>
    </section>
  );
}
