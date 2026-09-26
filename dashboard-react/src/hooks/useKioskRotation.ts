// Kiosk mode's rotation clock (DASH-17, D-14). Placeholder pending implementation.

export const KIOSK_ROTATION_MS = 20000;

export type KioskViewName = "incidents" | "topology";

export function useKioskRotation(_intervalMs: number = KIOSK_ROTATION_MS): {
  view: KioskViewName;
  cycle: number;
} {
  throw new Error("not implemented");
}
