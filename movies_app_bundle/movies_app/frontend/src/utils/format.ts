// Display helpers. Decision (CLAUDE.md §3): USD, timestamps in UTC shown
// as-is, so every formatter pins timeZone to UTC and labels it.

const UTC = "UTC";

export function money(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

/** "Sat, Sep 6 · 6:00 PM UTC" */
export function dateTime(iso: string): string {
  const d = new Date(iso);
  const date = d.toLocaleDateString("en-US", {
    timeZone: UTC,
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  return `${date} · ${time(iso)}`;
}

/** "6:00 PM UTC" */
export function time(iso: string): string {
  const t = new Date(iso).toLocaleTimeString("en-US", {
    timeZone: UTC,
    hour: "numeric",
    minute: "2-digit",
  });
  return `${t} UTC`;
}

/** "Saturday, September 6" — used as a group heading */
export function longDate(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-US", {
    timeZone: UTC,
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

/** UTC calendar date "YYYY-MM-DD", for grouping showtimes by day */
export function dateKey(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10);
}

export function seatLabel(rowLabel: string, seatNumber: number): string {
  return `${rowLabel}${seatNumber}`;
}
