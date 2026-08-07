/** Resolve browser motion/data preferences without importing GSAP or Lenis. */
export interface MotionPrefs {
  reduced: boolean;
  saveData: boolean;
  lowPower: boolean;
}

export function getMotionPrefs(): MotionPrefs {
  if (typeof window === "undefined") {
    return { reduced: false, saveData: false, lowPower: false };
  }

  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  const saveData = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData ?? false;
  const cores = navigator.hardwareConcurrency ?? 4;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4;
  const isMobile = /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent);

  return {
    reduced,
    saveData,
    lowPower: cores <= 2 || memory <= 2 || isMobile,
  };
}
