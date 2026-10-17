import { version } from "../package.json";
import { useLaya } from "./useLaya";
import { ClockStrip } from "./components/ClockStrip";
import { ProbBar } from "./components/ProbBar";
import { BookPanel } from "./components/BookPanel";
import { SizingPanel } from "./components/SizingPanel";
import { TradeLog } from "./components/TradeLog";

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <img src="/quantlabs.svg" alt="Logo Quantlabs" width={48} height={48} className="shrink-0" />
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.25em] text-muted">Quantlabs</p>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">Quantlabs LY-KY-Q</h1>
          <span className="num rounded border border-line px-1.5 py-0.5 text-[10px] text-muted" aria-label={`Versión ${version}`}>v{version}</span>
        </div>
        <p className="mt-0.5 text-xs text-muted">BTC · Mercados de 5 minutos</p>
      </div>
    </div>
  );
}

function Notice({ title, body }: { title: string; body: string }) {
  return (
    <main className="mx-auto max-w-xl px-6 py-24">
      <Brand />
      <h1 className="mt-8 text-2xl font-semibold">{title}</h1>
      <p className="mt-3 text-muted">{body}</p>
    </main>
  );
}

export default function App() {
  const { snap, connected, setConfig } = useLaya();

  if (!connected && !snap)
    return <Notice title="Sin conexión con el motor" body="Inicia el backend con `python server.py` en la carpeta backend. El panel se reconecta solo." />;
  if (!snap) return <Notice title="Conectando…" body="Esperando el primer dato del motor." />;
  if (snap.type === "status")
    return snap.phase === "error"
      ? <Notice title="El motor no pudo arrancar" body={snap.message} />
      : <Notice title={snap.phase === "training" ? "Entrenando modelos" : "Preparando datos"} body={snap.message} />;

  const t = snap;
  return (
    <div className="mx-auto max-w-6xl px-5 py-8">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-5">
        <Brand />
        <p className="flex items-center gap-2 text-sm text-muted">
          <span className={`inline-block h-2 w-2 rounded-full ${connected ? "bg-up" : "bg-down"}`} />
          {connected ? "Conectado" : "Reconectando…"} · precio: {t.price.source} · cuotas: {t.market.source === "polymarket" ? "Polymarket" : "simuladas"}
        </p>
      </header>

      <ClockStrip t={t} />

      <div className="mt-8 grid gap-10 lg:grid-cols-[1fr_320px]">
        <div className="space-y-10">
          <ProbBar t={t} />
          <BookPanel t={t} />
          <TradeLog t={t} />
        </div>
        <aside className="lg:border-l lg:border-line lg:pl-8">
          <SizingPanel t={t} onConfig={setConfig} />
        </aside>
      </div>

      <footer className="mt-12 border-t border-line pt-4 text-xs text-muted">
        Solo paper trading. Las probabilidades salen de un modelo entrenado con pocos días de datos y no son una promesa de rendimiento.
      </footer>
    </div>
  );
}
