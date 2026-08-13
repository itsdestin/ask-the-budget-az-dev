import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { GuidancePanel } from "./GuidancePanel";

// The panel owns its own fetch and its own save — it never rides the page's
// settings draft. What these specs protect:
//
//  1. The box shows what is ON DISK, and after a save it shows what the
//     SERVER returned. A local echo would let an admin walk away believing
//     text was stored that the server trimmed or rejected.
//  2. The two honesty sentences. These edits bypass the eval harness, so
//     "ask a few test questions" is the only real check there is, and
//     "changes apply to new conversations" is the difference between an
//     admin thinking the edit is broken and knowing it is queued.
//  3. The size meter. The cap exists so a runaway paste can't quietly
//     inflate every request's bill; a cap with no visible meter is a
//     rejection nobody saw coming.

function guidance(over: Partial<api.AdminGuidance> = {}): api.AdminGuidance {
  return {
    text: "Prefer the AFR for actual spending.",
    max_bytes: 8192,
    edited_by: "Destin",
    edited_at: "2026-08-01T17:00:00Z",
    ...over,
  };
}

/** Open the panel's collapsible card. Everything is behind it by design —
 *  the page reads as a table of contents until something is asked for. */
function openCard() {
  fireEvent.click(screen.getByRole("button", { name: /office guidance/i }));
}

afterEach(() => vi.restoreAllMocks());

async function renderPanel(over: Partial<api.AdminGuidance> = {}) {
  vi.spyOn(api, "adminGuidance").mockResolvedValue(guidance(over));
  render(<GuidancePanel />);
  await screen.findByTestId("admin-guidance");
  openCard();
}

describe("the office guidance box", () => {
  it("shows the text that is on disk", async () => {
    await renderPanel();
    expect(screen.getByLabelText(/office guidance/i)).toHaveValue(
      "Prefer the AFR for actual spending.",
    );
  });

  it("cannot be saved until something is changed", async () => {
    await renderPanel();

    const save = screen.getByRole("button", { name: /save guidance/i });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/office guidance/i), {
      target: { value: "Prefer the AFR for actual spending. Ask for the year." },
    });
    expect(save).toBeEnabled();
  });

  it("shows what was saved, as the server returned it", async () => {
    await renderPanel();
    // The server trims — so a panel that echoed the typed text would show
    // trailing whitespace that isn't there, and the next "unchanged" check
    // would be wrong too.
    vi.spyOn(api, "saveAdminGuidance").mockResolvedValue(
      guidance({ text: "Trimmed by the server.", edited_by: "Destin" }),
    );

    fireEvent.change(screen.getByLabelText(/office guidance/i), {
      target: { value: "  Trimmed by the server.   " },
    });
    fireEvent.click(screen.getByRole("button", { name: /save guidance/i }));

    await waitFor(() =>
      expect(screen.getByLabelText(/office guidance/i)).toHaveValue(
        "Trimmed by the server.",
      ),
    );
    expect(screen.getByRole("button", { name: /save guidance/i })).toBeDisabled();
  });

  it("says the edit reaches new conversations, and to spot-check it", async () => {
    await renderPanel();
    const panel = screen.getByTestId("admin-guidance");

    expect(panel).toHaveTextContent(/Changes apply to new conversations/i);
    expect(panel).toHaveTextContent(
      /This text shapes AI answers for the whole office/i,
    );
    expect(panel).toHaveTextContent(/ask a few test questions to check the effect/i);
  });

  it("shows how much room is left", async () => {
    await renderPanel({ text: "12345", max_bytes: 8192 });
    // Bytes, not characters — the backend's cap and its refusal message are
    // both byte-denominated, and pasted curly quotes/em dashes cost 3 bytes
    // each, so "characters" would visibly disagree with the real count.
    expect(screen.getByTestId("admin-guidance-size")).toHaveTextContent(
      "5 / 8,192 bytes",
    );
  });

  it("warns when the text is nearly at the limit", async () => {
    await renderPanel({ text: "x", max_bytes: 100 });

    expect(screen.getByTestId("admin-guidance-size")).not.toHaveTextContent(
      /close to the limit/i,
    );

    fireEvent.change(screen.getByLabelText(/office guidance/i), {
      target: { value: "y".repeat(95) },
    });
    // Said in words, not only in colour — the admin who is about to lose a
    // paste needs to be told, not hinted at.
    expect(screen.getByTestId("admin-guidance-size")).toHaveTextContent(
      /close to the limit/i,
    );
  });

  it("shows the server's own sentence when a save is refused", async () => {
    await renderPanel();
    vi.spyOn(api, "saveAdminGuidance").mockRejectedValue(
      new Error("save office guidance: That guidance is too long — keep it under 8 KB."),
    );

    fireEvent.change(screen.getByLabelText(/office guidance/i), {
      target: { value: "far too much text" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save guidance/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/keep it under 8 KB/);
    // Nothing was stored, so the typed text must still be there to fix.
    expect(screen.getByLabelText(/office guidance/i)).toHaveValue("far too much text");
  });

  it("says so when the guidance cannot be loaded at all", async () => {
    vi.spyOn(api, "adminGuidance").mockRejectedValue(
      new Error("load office guidance failed: 500"),
    );
    render(<GuidancePanel />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /load office guidance/i,
    );
  });
});
