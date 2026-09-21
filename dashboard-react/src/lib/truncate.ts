// Middle-truncation for device identifiers (D-35). A live screenshot showed every host on
// the operator's fleet as `192.168.0.x`, so a plain tail-clip left `.event-device-name`
// reading `1…` for EVERY row -- the distinguishing octet lives at the END of the string,
// not the start. This helper always keeps both ends and drops the middle, biasing the
// leftover character (on an odd budget) to the TAIL so that bias is never "simplified" away
// by someone assuming a head-heavy split is equivalent.
//
// No DOM access, no broker connection -- a pure function only.

export function middleTruncate(value: string, maxLength: number): string {
  if (typeof value !== "string" || value.length === 0 || maxLength <= 0) {
    return "";
  }
  if (value.length <= maxLength) {
    return value;
  }
  const budget = maxLength - 1; // reserve one character for the ellipsis (U+2026)
  const headLen = Math.floor(budget / 2);
  const tailLen = budget - headLen; // odd budgets give the extra character to the tail
  const head = value.slice(0, headLen);
  const tail = tailLen > 0 ? value.slice(value.length - tailLen) : "";
  return `${head}…${tail}`;
}
