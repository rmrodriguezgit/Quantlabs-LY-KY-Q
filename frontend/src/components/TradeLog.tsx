import type { Tick, Trade } from "../types";
import { hhmm, pct, usd } from "../format";

function Row({ x }: { x: Trade }) {
  const tone = x.status === "open" ? "" : x.win ? "text-up" : "text-down";
  return (
    <tr className="border-t border-line/70">
      <td className="num py-2">{hhmm(x.window_start)}</td>
      <td className="py-2">{x.side === "UP" ? "Up" : "Down"}</td>
      <td className="num py-2 text-right">{(x.entry * 100).toFixed(0)}¢</td>
      <td className="num py-2 text-right">{usd(x.stake)}</td>
      <td className="py-2 text-right">{x.status === "open" ? "abierta" : x.win ? "ganada" : "perdida"}</td>
      <td className={`num py-2 text-right ${tone}`}>{x.pnl == null ? "—" : usd(x.pnl)}</td>
    </tr>
  );
}

export function TradeLog({ t }: { t: Tick }) {
  const m = t.metrics;
  const rows = [...(t.open_trade ? [t.open_trade] : []), ...t.trades];
  return (
    <section aria-label="Bitácora de operaciones">
      <h2 className="text-lg font-semibold">Bitácora (paper trading)</h2>
      <dl className="mt-3 grid grid-cols-2 gap-x-8 gap-y-3 text-sm sm:grid-cols-4">
        <div><dt className="text-muted">Operaciones cerradas</dt><dd className="num text-lg">{m.n}</dd></div>
        <div><dt className="text-muted">Aciertos</dt><dd className="num text-lg">{pct(m.win_rate, 0)}</dd></div>
        <div><dt className="text-muted">Ganancia total</dt><dd className={`num text-lg ${m.pnl >= 0 ? "text-up" : "text-down"}`}>{usd(m.pnl)}</dd></div>
        <div><dt className="text-muted">Sharpe por operación</dt><dd className="num text-lg">{m.sharpe == null ? "—" : m.sharpe.toFixed(2)}</dd></div>
      </dl>
      {rows.length === 0 ? (
        <p className="mt-4 text-sm text-muted">Todavía no hay operaciones. El motor abre como máximo una por vela cuando la señal se mantiene tres lecturas seguidas.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[480px] text-sm">
            <thead>
              <tr className="text-left text-muted">
                <th className="font-normal">Vela</th><th className="font-normal">Lado</th>
                <th className="text-right font-normal">Entrada</th><th className="text-right font-normal">Monto</th>
                <th className="text-right font-normal">Estado</th><th className="text-right font-normal">Resultado</th>
              </tr>
            </thead>
            <tbody>{rows.map((x) => <Row key={`${x.id}-${x.status}`} x={x} />)}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}
