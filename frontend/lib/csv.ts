// OWASP CSV-injection guard: a field opened in Excel/Sheets that starts with one
// of these characters is interpreted as a formula (e.g. "=HYPERLINK(...)"). Both
// exports below include semi-trusted data (module names from scanned composer.json,
// AI-written finding messages, CVE advisory text) — prefix with a single quote so
// spreadsheet apps render it as literal text instead of evaluating it.
const FORMULA_TRIGGER_RE = /^[=+\-@\t\r]/;

export function escapeCsvField(v: unknown): string {
  // v is `unknown` by design (toCsv's own rows: unknown[][]) -- String(v)
  // only does the right thing for a primitive; an object/array would
  // otherwise silently become the literal text "[object Object]" in the
  // exported file rather than something a reader could make sense of.
  let s: string;
  if (v === null || v === undefined) {
    s = "";
  } else if (typeof v === "object") {
    s = JSON.stringify(v);
  } else {
    // The object/array case (the one this rule exists to catch) is already
    // handled explicitly above -- only string/number/boolean/symbol/bigint/
    // function narrow here, none of which use Object's default toString().
    // eslint-disable-next-line @typescript-eslint/no-base-to-string
    s = String(v);
  }
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
