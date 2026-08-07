/** Minimal cn utility — clsx + tailwind-merge (no @soymutdb/ui dependency). */
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs));
}