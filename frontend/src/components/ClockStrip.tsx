import { useEffect, useState } from "react";
import type { Tick } from "../types";
import { signed, usd } from "../format";

/** Reloj de la vela de 5 min: cinco tramos de un minuto que se llenan hasta el cierre. */
export function ClockStrip({ t }: { t: Tick }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), 250);
    return () => window.clearInterval(id);
  }, []);

  const left = Math.max(0, t.window.end - now);
  const elapsed = 300 - left;
  const mm = Math.floor(left / 60);
  const ss = Math.floor(left % 60);
  const above = t.price.distance_pct >= 0;

  return (
    <section className="grid gap-6 border-b border-line pb-6 md:grid-cols-[1fr_auto] md:items-end">
      <div>
        <div role="timer" aria-live="off" className="num text-6xl font-medium leading-none md:text-7xl">
          {mm}:{String(ss).padStart(2, "0")}
        </div>
        <p className="mt-2 text-sm text-muted">para el cierre de la vela de 5 minutos</p>
        <div className="mt-4 flex gap-1" aria-hidden>
          {[0, 1, 2, 3, 4].map((i) => {
            const fill = Math.min(1, Math.max(0, (elapsed - i * 60) / 60));
            return (
              <div key={i} className="h-2 flex-1 bg-line/60">
                <div className="h-full bg-ink" style={{ width: `${fill * 100}%` }} />
              </div>
            );
          })}
        </div>
      </div>
      <dl className="grid grid-cols-3 gap-x-8 gap-y-1 text-sm md:text-right">
        <dt className="text-muted">BTC ahora</dt>
        <dt className="text-muted">Precio a superar{t.price.strike_approx ? " (aprox.)" : ""}</dt>
        <dt className="text-muted">Distancia</dt>
        <dd className="num text-xl">{usd(t.price.spot, 0)}</dd>
        <dd className="num text-xl">{usd(t.price.strike, 0)}</dd>
        <dd className={`num text-xl ${above ? "text-up" : "text-down"}`}>{signed(t.price.distance_pct, 3)}%</dd>
      </dl>
    </section>
  );
}
