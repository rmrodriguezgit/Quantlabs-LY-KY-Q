import type { Book, Tick } from "../types";
import { cents, pct } from "../format";

function Side({ name, book, tone, yieldPct }: { name: string; book: Book; tone: string; yieldPct: number }) {
  return (
    <div>
      <h3 className={`font-semibold ${tone}`}>{name}</h3>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-sm">
        <div><dt className="text-muted">Compra a</dt><dd className="num text-lg">{cents(book.ask)}</dd></div>
        <div><dt className="text-muted">Venta a</dt><dd className="num text-lg">{cents(book.bid)}</dd></div>
        <div><dt className="text-muted">Rendimiento si gana</dt><dd className="num text-lg">{pct(yieldPct, 0)}</dd></div>
      </dl>
      {book.asks.length > 0 && (
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-muted"><th className="font-normal">Ofertas de venta</th><th className="text-right font-normal">Acciones</th></tr>
          </thead>
          <tbody>
            {book.asks.map(([p, sz], i) => (
              <tr key={i} className="border-t border-line/70">
                <td className="num py-1">{cents(p)}</td>
                <td className="num py-1 text-right">{sz ? sz.toFixed(0) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function BookPanel({ t }: { t: Tick }) {
  const m = t.market;
  return (
    <section aria-label="Libro de Polymarket">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Libro de Polymarket</h2>
        <span className="num text-xs text-muted">{m.slug ?? "sin mercado conectado"}</span>
      </div>
      {m.source === "simulated" && (
        <p className="mt-2 border-l-2 border-warn pl-3 text-sm text-warn">
          Estas cuotas son simuladas: no se pudo leer el mercado real. Las señales de este modo no sirven como evidencia.
        </p>
      )}
      <div className="mt-4 grid gap-8 sm:grid-cols-2">
        <Side name="Up" book={m.up} tone="text-up" yieldPct={t.signal.implied_yield_up} />
        <Side name="Down" book={m.down} tone="text-down" yieldPct={t.signal.implied_yield_down} />
      </div>
    </section>
  );
}
