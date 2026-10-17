import type { Tick } from "../types";
import { cents, pct, signed } from "../format";

const LABEL: Record<string, string> = { WAIT: "Esperar", BUY_UP: "Comprar Up", BUY_DOWN: "Comprar Down" };

/** Elemento central: la probabilidad del modelo frente a lo que el mercado está cobrando. */
export function ProbBar({ t }: { t: Tick }) {
  const s = t.signal;
  const marketUp = (s.ask_up + (1 - s.ask_down)) / 2;
  const tone = s.side === "UP" ? "text-up" : s.side === "DOWN" ? "text-down" : "text-ink";

  return (
    <section aria-label="Modelo frente a mercado">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Modelo frente a mercado</h2>
        <p className={`text-2xl font-semibold ${tone}`}>
          {LABEL[s.action]}
          {s.laya_veto && <span className="ml-2 text-sm font-normal text-warn">vetado por Laya</span>}
        </p>
      </div>

      <div className="relative mt-5 h-14 overflow-visible">
        <div className="flex h-full w-full overflow-hidden">
          <div className="bg-up transition-[width] duration-500" style={{ width: `${s.p_up * 100}%` }} />
          <div className="flex-1 bg-down" />
        </div>
        <span className="num absolute left-3 top-1/2 -translate-y-1/2 text-lg text-white">{pct(s.p_up)}</span>
        <span className="num absolute right-3 top-1/2 -translate-y-1/2 text-lg text-white">{pct(s.p_down)}</span>
        <div
          className="absolute -top-2 -bottom-2 w-0.5 bg-ink transition-[left] duration-500"
          style={{ left: `${marketUp * 100}%` }}
          aria-hidden
        />
        <span
          className="num absolute -top-7 -translate-x-1/2 whitespace-nowrap text-xs text-ink"
          style={{ left: `${marketUp * 100}%` }}
        >
          mercado {pct(marketUp, 0)}
        </span>
      </div>
      <div className="mt-2 flex justify-between text-sm text-muted">
        <span>Sube (Up)</span>
        <span>Baja (Down)</span>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-x-8 gap-y-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-muted">Ventaja en Up</dt>
          <dd className={`num text-lg ${s.edge_up > 0 ? "text-up" : ""}`}>{signed(s.edge_up * 100)} pts</dd>
        </div>
        <div>
          <dt className="text-muted">Ventaja en Down</dt>
          <dd className={`num text-lg ${s.edge_down > 0 ? "text-down" : ""}`}>{signed(s.edge_down * 100)} pts</dd>
        </div>
        <div>
          <dt className="text-muted">Valor Q (esperar / Up / Down)</dt>
          <dd className="num text-lg">{s.q.map((x) => x.toFixed(2)).join(" / ")}</dd>
        </div>
        <div>
          <dt className="text-muted">Compuerta Laya</dt>
          <dd className="num text-lg">{t.config.use_laya ? (s.laya_p == null ? "sin lectura" : pct(s.laya_p, 0)) : "apagada"}</dd>
        </div>
      </dl>
      <p className="mt-3 text-xs text-muted">
        Precio de compra actual: Up {cents(s.ask_up)}, Down {cents(s.ask_down)}. La ventaja es probabilidad del modelo menos ese precio.
      </p>
    </section>
  );
}
