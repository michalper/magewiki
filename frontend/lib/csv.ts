// OWASP CSV-injection guard: a field opened in Excel/Sheets that starts with one
// of these characters is interpreted as a formula (e.g. "=HYPERLINK(...)"). Both
// exports below include semi-trusted data (module names from scanned composer.json,
// AI-written finding messages, CVE advisory text) — prefix with a single quote so
// spreadsheet apps render it as literal text instead of evaluating it.
const FORMULA_TRIGGER_RE = /^[=+\-@\t\r]/;

export function escapeCsvField(v: unknown): string {
  let s = v === null || v === undefined ? "" : String(v);
  if (FORMULA_TRIGGER_RE.test(s)) {
    s = `'${s}`;
  }
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(headers: string[], rows: unknown[][]): string {
  return [headers, ...rows].map((row) => row.map(escapeCsvField).join(",")).join("\n");
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
