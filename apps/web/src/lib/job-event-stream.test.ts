/**
 * The job event stream must never carry the access token in its URL.
 *
 * `EventSource` cannot send headers, and the edge proxy logs the request line
 * including the query string, so the URL credential is a single-use ticket
 * exchanged over an authenticated POST instead.
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  secureRequest: vi.fn(),
}));

vi.mock("./api", () => ({
  apiBaseUrl: "/api/v1",
  secureRequest: api.secureRequest,
}));

import { jobEventStreamUrl, openJobEventStream, requestJobEventTicket } from "./job-event-stream";

const opened: string[] = [];

class RecordingEventSource {
  url: string;
  closed = false;

  constructor(url: string) {
    this.url = url;
    opened.push(url);
  }

  addEventListener() {}

  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  api.secureRequest.mockReset();
  opened.length = 0;
  vi.stubGlobal("EventSource", RecordingEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("exchanges the session for a ticket over an authenticated POST", async () => {
  api.secureRequest.mockResolvedValue({ ticket: "ticket-value", expires_in: 30 });

  const ticket = await requestJobEventTicket();

  expect(ticket.ticket).toBe("ticket-value");
  expect(api.secureRequest).toHaveBeenCalledWith("/jobs/sse-ticket", { method: "POST" });
});

it("puts the ticket — never the access token — in the stream URL", () => {
  const url = new URL(jobEventStreamUrl("ticket-value"));

  expect(url.pathname).toBe("/api/v1/jobs/events");
  expect(url.searchParams.get("ticket")).toBe("ticket-value");
  expect(url.searchParams.has("access_token")).toBe(false);
  expect(url.search).not.toContain("access_token");
});

it("opens EventSource with the issued ticket", async () => {
  api.secureRequest.mockResolvedValue({ ticket: "ticket-value", expires_in: 30 });

  const stream = (await openJobEventStream()) as unknown as RecordingEventSource;

  expect(api.secureRequest).toHaveBeenCalledTimes(1);
  expect(opened).toHaveLength(1);
  expect(stream.url).toBe(jobEventStreamUrl("ticket-value"));
  expect(new URL(stream.url).searchParams.get("ticket")).toBe("ticket-value");
});

it("rejects without opening a stream when no ticket can be issued", async () => {
  api.secureRequest.mockRejectedValue(new Error("not authenticated"));

  await expect(openJobEventStream()).rejects.toThrow("not authenticated");
  expect(opened).toHaveLength(0);
});