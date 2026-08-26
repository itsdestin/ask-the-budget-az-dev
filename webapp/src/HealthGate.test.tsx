import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { HealthGate } from "./HealthGate";

// The failure screen is the only surface in this product whose reader is
// someone whose app will not start. What is pinned here:
//
//   * A healthy ladder renders the app with NO flash of the gate.
//   * A failing rung renders full-page with the sentence and the fix, and
//     NO stack trace, JSON or error code.
//   * The short-circuited rungs below the failure stay silent — printing
//     "not checked" three times would bury the one line that matters.
//   * The repair box appears only when relocating can help, and on success
//     says to check again — never to restart or reopen the app (2026-08-25:
//     the server now swaps the folder in place; see Repair.tsx).

function rung(over: Partial<api.HealthRung> = {}): api.HealthRung {
  return { name: "share", ok: true, detail: "fine", fix: null, ...over };
}

const HEALTHY: api.HealthReport = {
  ok: true,
  rungs: [
    rung({ name: "server" }),
    rung({ name: "machine_config" }),
    rung({ name: "share" }),
    rung({ name: "corpus" }),
    rung({ name: "models" }),
  ],
  data_dir: "/share/jlbc-insight-data",
  can_repair: false,
  can_pick: false,
};

const SHARE_GONE: api.HealthReport = {
  ok: false,
  rungs: [
    rung({ name: "server" }),
    rung({ name: "machine_config" }),
    rung({
      name: "share",
      ok: false,
      detail: "Can't find S:\\jlbc-insight-data. Check the network drive is connected, or choose the folder again.",
      fix: null,
    }),
    rung({ name: "corpus", ok: null, detail: "Not checked — fix the problem above first." }),
    rung({ name: "models", ok: null, detail: "Not checked — fix the problem above first." }),
  ],
  data_dir: "S:\\jlbc-insight-data",
  can_repair: true,
  can_pick: false,
};

const CORPUS_BROKEN: api.HealthReport = {
  ok: false,
  rungs: [
    rung({ name: "server" }),
    rung({ name: "machine_config" }),
    rung({ name: "share" }),
    rung({
      name: "corpus",
      ok: false,
      detail: "JLBC Search can't open the data in /share/wrong-folder. Ask whoever maintains it.",
      fix: null,
    }),
    rung({ name: "models", ok: null, detail: "Not checked — fix the problem above first." }),
  ],
  data_dir: "/share/wrong-folder",
  can_repair: false,
  can_pick: false,
};

function App() {
  return <p>the real app</p>;
}

afterEach(() => vi.restoreAllMocks());

describe("a healthy ladder", () => {
  it("renders the app", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue(HEALTHY);
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    expect(await screen.findByText("the real app")).toBeInTheDocument();
    expect(screen.queryByTestId("repair")).toBeNull();
  });

  it("shows no flash of the gate while the check is in flight", () => {
    // Never resolves — the state DURING the check.
    vi.spyOn(api, "healthDetail").mockReturnValue(new Promise(() => {}));
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    // The healthy case is overwhelmingly the common one; a spinner in front
    // of every launch would tax every working start to tidy up a rare
    // broken one.
    expect(screen.getByText("the real app")).toBeInTheDocument();
    expect(screen.queryByTestId("repair")).toBeNull();
  });
});

describe("a failing rung", () => {
  it("replaces the app with the sentence and the fix", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue(SHARE_GONE);
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );

    await screen.findByTestId("repair");
    expect(screen.queryByText("the real app")).toBeNull();
    expect(screen.getByText(/Can't find S:/)).toBeInTheDocument();
    expect(screen.getByText(/choose the folder again/)).toBeInTheDocument();
  });

  it("shows no stack trace, JSON or error code", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue(SHARE_GONE);
    const { container } = render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    await screen.findByTestId("repair");

    const text = container.textContent ?? "";
    for (const forbidden of ["Traceback", "{", "}", "Error:", "500", "null"]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it("stays silent about the rungs it never checked", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue(SHARE_GONE);
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    await screen.findByTestId("repair");

    // One problem, one line. Repeating "not checked" under it would bury
    // the sentence that matters.
    expect(screen.getAllByTestId("repair-rung")).toHaveLength(1);
    expect(screen.queryByText(/Not checked/)).toBeNull();
  });
});

describe("the repair box", () => {
  it("is offered when relocating the folder can help", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue(SHARE_GONE);
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    expect(await screen.findByTestId("repair-form")).toBeInTheDocument();
    // Prefilled with where it is currently looking, so the reader can see
    // what is wrong with it rather than retyping from nothing.
    expect(screen.getByLabelText(/type its location/i)).toHaveValue("S:\\jlbc-insight-data");
  });

  it("offers Choose folder… when the server can open a dialog, and saves the pick", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue({ ...SHARE_GONE, can_pick: true });
    vi.spyOn(api, "pickFolder").mockResolvedValue({ supported: true, path: "\\\\bcpool\\JLBCSearch" });
    const save = vi.spyOn(api, "setDataDir").mockResolvedValue({ path: "\\\\bcpool\\JLBCSearch" });
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /choose folder/i }));
    await screen.findByTestId("repair-done");
    expect(save).toHaveBeenCalledWith("\\\\bcpool\\JLBCSearch");
  });

  it("hides Choose folder… when the server cannot open a dialog", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue({ ...SHARE_GONE, can_pick: false });
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    await screen.findByTestId("repair-form");
    expect(screen.queryByRole("button", { name: /choose folder/i })).toBeNull();
  });

  it("a cancelled dialog leaves the form as it was", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue({ ...SHARE_GONE, can_pick: true });
    vi.spyOn(api, "pickFolder").mockResolvedValue({ supported: true, path: null });
    const save = vi.spyOn(api, "setDataDir");
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /choose folder/i }));
    await screen.findByRole("button", { name: /choose folder/i });
    expect(save).not.toHaveBeenCalled();
  });

  it("is NOT offered when relocating cannot help", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue(CORPUS_BROKEN);
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    await screen.findByTestId("repair");
    // Offering it here would walk someone through a fix that cannot work.
    expect(screen.queryByTestId("repair-form")).toBeNull();
    expect(screen.getByText(/can't open the data/)).toBeInTheDocument();
  });

  it("after saving, says to check again — never to restart", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue(SHARE_GONE);
    vi.spyOn(api, "setDataDir").mockResolvedValue({ path: "\\\\newserver\\share" });
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );

    fireEvent.change(await screen.findByLabelText(/type its location/i), {
      target: { value: "\\\\newserver\\share" },
    });
    fireEvent.click(screen.getByRole("button", { name: /use this folder/i }));

    const done = await screen.findByTestId("repair-done");
    // The launcher reuses a running server, so "reopen the app" did nothing
    // (2026-08-25). The server swaps in place; the button re-runs the ladder.
    expect(done).toHaveTextContent(/Saved/);
    expect(done).toHaveTextContent(/Check again/);
    expect(done).not.toHaveTextContent(/open JLBC Search again/i);
  });

  it("offers the folder box when the pointer file itself is the problem", async () => {
    const POINTER_BROKEN: api.HealthReport = {
      ok: false,
      rungs: [
        rung({ name: "server" }),
        rung({
          name: "machine_config",
          ok: false,
          detail: "No location is set on this computer yet.",
          fix: null,
        }),
        rung({ name: "share", ok: null, detail: "Not checked — fix the problem above first." }),
        rung({ name: "corpus", ok: null, detail: "Not checked — fix the problem above first." }),
        rung({ name: "models", ok: null, detail: "Not checked — fix the problem above first." }),
      ],
      data_dir: null,
      can_repair: true,
      can_pick: false,
    };
    vi.spyOn(api, "healthDetail").mockResolvedValue(POINTER_BROKEN);
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    await screen.findByTestId("repair-form");
    // WHY: pin the EXACT rendered string, not just that a placeholder exists.
    // A JSX attribute string literal doesn't process backslash escapes, so a
    // regression back to placeholder="..." would render four leading
    // backslashes instead of two and this assertion is what catches it.
    const box = screen.getByPlaceholderText(/jlbc-search-data/) as HTMLInputElement;
    expect(box.placeholder).toBe("\\\\server\\share\\jlbc-search-data");
  });

  it("surfaces the server's own rejection sentence", async () => {
    vi.spyOn(api, "healthDetail").mockResolvedValue(SHARE_GONE);
    vi.spyOn(api, "setDataDir").mockRejectedValue(
      new Error(
        "set data folder: That folder doesn't contain a JLBC Search corpus (no lancedb folder inside).",
      ),
    );
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );

    fireEvent.change(await screen.findByLabelText(/type its location/i), {
      target: { value: "/wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: /use this folder/i }));

    // "Can't find that folder" and "that folder has no corpus in it" send the
    // reader to different next actions, so the distinction has to survive.
    expect(await screen.findByTestId("repair-error")).toHaveTextContent(
      /no lancedb folder inside/,
    );
  });

  it("re-checks on demand", async () => {
    const check = vi.spyOn(api, "healthDetail").mockResolvedValue(SHARE_GONE);
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );
    await screen.findByTestId("repair");

    check.mockResolvedValue(HEALTHY);
    fireEvent.click(screen.getByRole("button", { name: /check again/i }));

    expect(await screen.findByText("the real app")).toBeInTheDocument();
  });
});

describe("when the server itself is not answering", () => {
  it("says only what is certainly true", async () => {
    vi.spyOn(api, "healthDetail").mockRejectedValue(new Error("health check failed: 503"));
    render(
      <HealthGate>
        <App />
      </HealthGate>,
    );

    await screen.findByTestId("repair");
    expect(screen.getByText(/isn't responding on this computer/i)).toBeInTheDocument();
    // No repair box: nothing about a folder can fix a server that is down.
    expect(screen.queryByTestId("repair-form")).toBeNull();
    // And no raw error text from the fetch layer.
    expect(screen.queryByText(/503/)).toBeNull();
  });
});
