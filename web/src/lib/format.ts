// Number formats shared across features.

const LAKH = 100_000

/**
 * A people estimate in Indian units: 1,23,456 -> "~1.2 lakh", 8,400 -> "~8,000",
 * 420 -> "<1,000", 0 -> "0".
 */
export function formatPeople(n: number): string {
  if (n <= 0) return '0'
  if (n < 1000) return '<1,000'
  const thousands = Math.round(n / 1000) * 1000
  if (thousands < LAKH) return `~${thousands.toLocaleString('en-IN')}`
  return `~${(n / LAKH).toFixed(1)} lakh`
}
