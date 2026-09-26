import type { Usage } from "./api";

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

function euros(eur: number): string {
  return eur.toLocaleString("de", { style: "currency", currency: "EUR", maximumFractionDigits: eur < 0.1 ? 3 : 2 });
}

/** Token usage and approximate cost: on one line, or with `stacked` on one line each for input, output, and cost. */
export default function Tokens({ usage, stacked = false }: { usage: Usage; stacked?: boolean }) {
  const exact = (n: number) => n.toLocaleString("en");
  const parts = [
    `↑ ${compact.format(usage.input)} (${compact.format(usage.cached)} cached)`,
    `↓ ${compact.format(usage.output)}`,
    `≈ ${euros(usage.eur)}`,
  ];
  return (
    <span className={stacked ? "tokens stacked" : "tokens"} title={
      `${exact(usage.input)} input tokens, ${exact(usage.cached)} of them cached; ${exact(usage.output)} output tokens`
    }>
      {stacked ? parts.map((p) => <span key={p}>{p}</span>) : parts.join(" · ")}
    </span>
  );
}
