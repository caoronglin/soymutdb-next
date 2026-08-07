import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind CSS class names with conflict resolution.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Format a large integer with locale-aware thousands separators.
 */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return new Intl.NumberFormat().format(value);
}

/**
 * Format a value as a percentage string with configurable decimals.
 */
export function formatPercent(
  value: number | null | undefined,
  decimals = 1,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(decimals)}%`;
}

/**
 * Format a byte size into a human-readable string.
 */
export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || bytes <= 0) {
    return "—";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

/**
 * Truncate a string to a maximum length, appending an ellipsis.
 */
export function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1)}…`;
}

// ---------------------------------------------------------------------------
// Password complexity validation
// ---------------------------------------------------------------------------

/** Character type categories for password complexity checking. */
export interface PasswordValidationResult {
  /** Whether the password meets all requirements (8+ chars, 3+ types). */
  valid: boolean;
  /** Number of character types present (0–4). */
  typeCount: number;
  /** Individual type checks. */
  hasUppercase: boolean;
  hasLowercase: boolean;
  hasDigit: boolean;
  hasSpecial: boolean;
  /** Whether length ≥ 8. */
  hasMinLength: boolean;
  /** Estimated strength score 0–4 for UI display. */
  score: 0 | 1 | 2 | 3 | 4;
}

/**
 * Validate password complexity per system security policy.
 *
 * Requirements:
 * - Minimum 8 characters
 * - At least 3 of 4 character types: uppercase, lowercase, digits, special
 */
export function validatePasswordStrength(password: string): PasswordValidationResult {
  const hasUppercase = /[A-Z]/.test(password);
  const hasLowercase = /[a-z]/.test(password);
  const hasDigit = /\d/.test(password);
  const hasSpecial = /[^A-Za-z0-9]/.test(password);
  const typeCount = [hasUppercase, hasLowercase, hasDigit, hasSpecial].filter(Boolean).length;
  const hasMinLength = password.length >= 8;

  const valid = hasMinLength && typeCount >= 3;

  // Score: 0 (empty) → 4 (strong). Based on length + type diversity.
  let score: 0 | 1 | 2 | 3 | 4 = 0;
  if (password.length === 0) score = 0;
  else if (password.length < 8) score = 1;
  else if (typeCount < 2) score = 1;
  else if (typeCount === 2) score = 2;
  else if (typeCount === 3 && password.length >= 10) score = 3;
  else if (typeCount >= 3 && password.length >= 12) score = 4;
  else score = 3;

  return { valid, typeCount, hasUppercase, hasLowercase, hasDigit, hasSpecial, hasMinLength, score };
}

/** Get a human-readable strength label from a score. */
export function getPasswordStrengthLabel(score: number): string {
  return ["Too short", "Weak", "Fair", "Good", "Strong"][score] ?? "Weak";
}
