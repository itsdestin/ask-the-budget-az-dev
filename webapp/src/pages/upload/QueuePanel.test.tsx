import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "../../api";
import { QueuePanel } from "./QueuePanel";

// Spec T13: the queue shows work, not history.
//
// jsdom applies no stylesheet, so nothing here says anything about how the
// panel LOOKS. These pin what it lists and what it says.

function job(over: Partial<api.Job> = {}): api.Job {
  return {
    job_id: "j1",
    doc_id: "jlbc-baseline-fy2027-axs",
    title: "FY 2027 Baseline — AHCCCS",
    corpus: "budget",
    state: "queued",
    pct: 0,
    stage_detail: "",
    error: null,
    machine: "JLBC-PC-4",
    user: "destin",
    created_at: "2026-08-13T00:00:00+00:00",
    updated_at: "2026-08-13T00:00:00+00:00",
    ...over,
  } as api.Job;
}

function body(over: Partial<api.JobsResponse> = {}): api.JobsResponse {
  return { jobs: [], finished_count: 0, showing: "active", ...over };
}

afterEach(() => vi.restoreAllMocks());

describe("when no computer is set to process uploads", () => {
  it("says so, above the rows that are not moving", async () => {
    // 🔴 The counterweight to the 2026-08-16 ingest-switch fix. The upload
    // and books routes no longer start the queue on a machine that opted
    // out, which is correct -- but without this an analyst queues a
    // document and watches "Waiting" for ever with nothing explaining why,
    // trading a CPU problem for a trust problem.
    const message =
      "Uploads are waiting and no computer is set to process them. Open JLBC " +
      "Insight on the computer that should do this work, go to Admin → " +
      'Corpus, and turn on "Process uploads on this computer".';
    vi.spyOn(api, "jobs").mockResolvedValue(
      body({ jobs: [job()], stalled_message: message }),
    );
    render(<QueuePanel />);

    const warning = await screen.findByTestId("queue-stalled");
    expect(warning.textContent).toBe(message);
    // Above the rows: a reader who has scrolled past them has already
    // formed the wrong conclusion about why nothing is moving.
    const row = await screen.findByTestId("job");
    expect(warning.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
  });

  it("renders the server's sentence VERBATIM, never a local paraphrase", async () => {
    // The same words the admin page shows, from one place on the server
    // (app/queue_status.py). A paraphrase here is how the two surfaces
    // would start telling an office two different things about one queue.
    vi.spyOn(api, "jobs").mockResolvedValue(
      body({ jobs: [job()], stalled_message: "SERVER SAYS THIS EXACT THING" }),
    );
    render(<QueuePanel />);
    expect((await screen.findByTestId("queue-stalled")).textContent)
      .toBe("SERVER SAYS THIS EXACT THING");
  });

  it("says nothing at all on the machine that does the work", async () => {
    vi.spyOn(api, "jobs").mockResolvedValue(
      body({ jobs: [job()], stalled_message: null }),
    );
    render(<QueuePanel />);
    await screen.findByTestId("job");
    expect(screen.queryByTestId("queue-stalled")).toBeNull();
  });

  it("says nothing when an older server omits the field entirely", async () => {
    // A server predating this must read as "no warning", not as a crash.
    vi.spyOn(api, "jobs").mockResolvedValue(body({ jobs: [job()] }));
    render(<QueuePanel />);
    await screen.findByTestId("job");
    expect(screen.queryByTestId("queue-stalled")).toBeNull();
  });
});

describe("the queue shows work, not history", () => {
  it("renders a failed job whatever its age", async () => {
    // 13 of the 14 failures in the live data dir were 12.6 days old. The
    // server sends them regardless of age and the panel must not re-filter.
    vi.spyOn(api, "jobs").mockResolvedValue(
      body({
        jobs: [job({ job_id: "old", state: "failed", error: "mineru exploded" })],
        finished_count: 7104,
      }),
    );
    render(<QueuePanel />);
    expect(await screen.findByText("mineru exploded")).toBeTruthy();
  });

  it("states how many documents finished, and never counts them itself", async () => {
    // The count comes off the wire precisely because the browser no longer
    // receives the 7,104 finished rows it would have to count.
    vi.spyOn(api, "jobs").mockResolvedValue(body({ jobs: [], finished_count: 7104 }));
    render(<QueuePanel />);
    expect(await screen.findByText(/7,104 documents have finished/)).toBeTruthy();
  });

  it("says nothing about finished documents when there are none", async () => {
    // A fresh install must not announce "0 documents have finished" — the
    // house rule this page already follows (see admin/NeedsAttention.tsx):
    // a line on screen every day teaches people to scroll past it.
    vi.spyOn(api, "jobs").mockResolvedValue(body({ jobs: [], finished_count: 0 }));
    render(<QueuePanel />);
    await screen.findByText("Nothing is processing right now.");
    expect(screen.queryByText(/finished/)).toBeNull();
  });

  it("view all asks the server for everything and says that is what it shows", async () => {
    // The fake ECHOES what it was asked for, exactly as the route does. An
    // earlier version of this spec returned `showing: "all"` unconditionally,
    // which flipped the component's own state and made a LATER poll request
    // everything -- so the assertion passed even with the button wired to the
    // wrong mode. Caught by mutating the button and watching it stay green.
    const list = vi.spyOn(api, "jobs").mockImplementation(async (all?: boolean) =>
      body({
        jobs: all ? [job({ job_id: "done", state: "live" })] : [],
        finished_count: 2,
        showing: all ? "all" : "active",
      }),
    );
    render(<QueuePanel />);
    await screen.findByRole("button", { name: /view all/i });
    list.mockClear();

    fireEvent.click(screen.getByRole("button", { name: /view all/i }));

    // The FIRST call after the click is the one the button made.
    await waitFor(() => expect(list.mock.calls[0]?.[0]).toBe(true));
    expect(await screen.findByText(/Showing everything, including 2 finished/)).toBeTruthy();
  });

  it("keeps a row that finished while this browser was watching it", async () => {
    // Spec T13 removed the server's 24-hour window, so a row would otherwise
    // vanish at the exact instant the analyst's own upload succeeded. The
    // browser knows what it was watching; the server does not.
    const running = job({ job_id: "mine", state: "embedding" });
    const finished = job({ job_id: "mine", state: "live" });
    let seen = false;
    vi.spyOn(api, "jobs").mockImplementation(async (all?: boolean) => {
      if (all) return body({ jobs: [finished], finished_count: 1, showing: "all" });
      // Second and later polls: the server has archived it, so it is gone.
      return body({
        jobs: seen ? [] : [running],
        finished_count: seen ? 1 : 0,
      });
    });
    const { rerender } = render(<QueuePanel reloadToken={0} />);
    expect(await screen.findByText("Building the search index")).toBeTruthy();

    seen = true;
    rerender(<QueuePanel reloadToken={1} />);

    // Still on screen, now reading as finished rather than simply gone.
    expect(await screen.findByText("Searchable")).toBeTruthy();
  });

  it("keeps the last good queue when a refresh fails", async () => {
    const list = vi
      .spyOn(api, "jobs")
      .mockResolvedValueOnce(body({ jobs: [job({ state: "embedding" })] }))
      .mockRejectedValue(new Error("share unavailable"));
    const { rerender } = render(<QueuePanel reloadToken={0} />);
    expect(await screen.findByText("Building the search index")).toBeTruthy();

    rerender(<QueuePanel reloadToken={1} />);
    await waitFor(() => expect(list.mock.calls.length).toBeGreaterThan(1));

    // A momentary share hiccup is not "no jobs".
    expect(screen.getByText("Building the search index")).toBeTruthy();
    expect(screen.getByText(/share unavailable/)).toBeTruthy();
  });

  it("offers Retry on a failure and Cancel on running work", async () => {
    vi.spyOn(api, "jobs").mockResolvedValue(
      body({
        jobs: [
          job({ job_id: "bad", state: "failed", error: "boom" }),
          job({ job_id: "busy", state: "embedding" }),
        ],
      }),
    );
    render(<QueuePanel />);
    const rows = await screen.findAllByTestId("job");
    expect(within(rows[0]).getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(within(rows[1]).getByRole("button", { name: "Cancel" })).toBeTruthy();
  });
});
