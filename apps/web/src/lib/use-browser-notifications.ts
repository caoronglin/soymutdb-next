/**
 * Browser Notification API wrapper (D2).
 *
 * The web channel of the notification system: OS-level browser
 * notifications for job completion events, layered on top of the in-app
 * bell. `ensurePermission()` must only ever be called from a user gesture
 * (e.g. a submit button click) — browsers reject silent permission
 * requests. `showNotification()` is a no-op unless permission is granted.
 */

export type NotificationPermissionState = "granted" | "denied" | "default";

/** True when the browser exposes the Notification API. */
export function isNotificationSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/** Current permission state ("default" when unsupported). */
export function getNotificationPermission(): NotificationPermissionState {
  if (!isNotificationSupported()) return "default";
  return Notification.permission;
}

/**
 * Request notification permission. Call ONLY from a user gesture
 * (click/keydown handler). Resolves to the resulting permission state;
 * "denied" when unsupported or the user refuses.
 */
export async function ensurePermission(): Promise<NotificationPermissionState> {
  if (!isNotificationSupported()) return "denied";
  if (Notification.permission === "granted" || Notification.permission === "denied") {
    return Notification.permission;
  }
  try {
    return await Notification.requestPermission();
  } catch {
    return "denied";
  }
}

/**
 * Show a browser notification; clicking it focuses the tab and opens
 * `link` when provided. Returns true when a notification was shown.
 * Fails silently when unsupported / permission not granted.
 */
export function showNotification(
  title: string,
  body: string,
  link?: string,
): boolean {
  if (!isNotificationSupported() || Notification.permission !== "granted") {
    return false;
  }
  try {
    const n = new Notification(title, { body });
    if (link) {
      n.onclick = () => {
        window.focus();
        window.location.href = link;
        n.close();
      };
    }
    return true;
  } catch {
    return false;
  }
}
