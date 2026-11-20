/**
 * Authenticated subscription to the job-status event stream.
 *
 * `GET /api/v1/jobs/events` is Server-Sent Events, and the browser
 * `EventSource` API cannot set an `Authorization` header — so the stream URL
 * needs a credential of its own. It must not be the access token: the edge
 * proxy logs the request line including the query string
 * (`infra/nginx/nginx.conf`), which would write a live session credential to
 * `access.log`.
 *
 * The transport is therefore a two-step exchange:
 *
 * 1. `POST /api/v1/jobs/sse-ticket` with the normal bearer session returns an
 *    opaque, single-use ticket bound server-side to the caller (TTL <= 60 s);
 * 2. `new EventSource(<events>?ticket=...)` redeems it exactly once.
 *
 * Only the ticket — never the access token — ever appears in a URL.
 */
import { apiBaseUrl, secureRequest } from "./api";

/** The stream credential returned by `POST /api/v1/jobs/sse-ticket`. */
export interface SseTicket {
  ticket: string;
  /** Seconds until the ticket expires; also invalidated by its first use. */
  expires_in: number;
}

/** Exchange the current session for one single-use stream ticket. */
export async function requestJobEventTicket(): Promise<SseTicket> {
  return secureRequest<SseTicket>("/jobs/sse-ticket", { method: "POST" });
}

/** Absolute URL of the event stream carrying `ticket` as its only credential. */
export function jobEventStreamUrl(ticket: string): string {
  const url = new URL(`${apiBaseUrl}/jobs/events`, window.location.origin);
  url.searchParams.set("ticket", ticket);
  return url.toString();
}

/**
 * Open the job-status stream for the current session.
 *
 * Rejects when the ticket exchange fails (expired session, or the ticket
 * store unavailable); the caller keeps its polling fallback in that case.
 */
export async function openJobEventStream(): Promise<EventSource> {
  const { ticket } = await requestJobEventTicket();
  return new EventSource(jobEventStreamUrl(ticket));
}