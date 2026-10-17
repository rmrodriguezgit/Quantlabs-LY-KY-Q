export const pct = (x: number | null | undefined, d = 1) =>
  x == null ? "—" : `${(x * 100).toFixed(d)}%`;
export const usd = (x: number | null | undefined, d = 2) =>
  x == null ? "—" : `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
export const signed = (x: number, d = 1) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(d)}`;
export const cents = (x: number | null | undefined) => (x == null ? "—" : `${(x * 100).toFixed(0)}¢`);
export const hhmm = (epoch: number) =>
  new Date(epoch * 1000).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });
