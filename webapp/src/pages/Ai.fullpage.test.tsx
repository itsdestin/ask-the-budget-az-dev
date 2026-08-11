// AI Mode is the ONLY pinned-viewport route (Destin, 2026-07-31).
//
// The retired Next.js app was a fixed-viewport chat shell: `html, body {
// overflow: hidden }` globally, one screen, the thread and the source panel
// scrolling internally. This app cannot do that globally — Home, Budget
// Documents, Fiscal Notes, Upload and Settings are ordinary scrolling pages,
// and a global `overflow:hidden` would strand their content below the fold
// with no way to reach it.
//
// So the pin is a CLASS the AI page puts on <html> while it is mounted and
// takes off again when it unmounts. These specs are what stop that from
// regressing into a global rule — which is a failure nobody would notice in
// AI Mode, because AI Mode would look perfect.
//
// Two kinds of proof here, because jsdom does no layout and therefore cannot
// tell us whether anything actually scrolled:
//   1. Behavioural — the class goes on at /ai and comes off on route change.
//   2. Source-level — every viewport-pinning declaration in app.css is
//      scoped under `html.ai-fullpage`. This is the one that catches "someone
//      moved overflow:hidden up to the base block", which spec 1 cannot see.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "../App";
import { Ai } from "./Ai";
import * as api from "../api";
import { AI_STATUS, stubConversationFetch, stubScrollIntoView } from "./ai-test-fixtures";

/** The class Ai.tsx puts on <html>. Duplicated from the page on purpose: if
 *  someone renames it there, this constant is what makes the rename show up as
 *  a failing spec rather than as a silently-unpinned page. */
const PIN = "ai-fullpage";

const pinned = () => document.documentElement.classList.contains(PIN);

function mountAt(path: string) {
  vi.spyOn(api, "aiStatus").mockResolvedValue(AI_STATUS);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  stubScrollIntoView();
  stubConversationFetch();
  document.documentElement.classList.remove(PIN);
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.classList.remove(PIN);
});

describe("AI Mode pins the viewport — and only AI Mode", () => {
  it("pins <html> while AI Mode is on screen", async () => {
    mountAt("/ai");
    await screen.findByTestId("ai-panel");
    expect(pinned()).toBe(true);
  });

  it("un-pins when the analyst navigates to another page", async () => {
    // Navigates via the LOGO. The header's house pill is gone (2026-08-02) —
    // the logo is now the only route home, which is exactly why it is worth
    // clicking here rather than picking some other pill.
    mountAt("/ai");
    await screen.findByTestId("ai-panel");
    expect(pinned()).toBe(true);

    // The header's Home pill — a real route change, which is how an analyst
    // actually leaves AI Mode. If the cleanup ever stops running, Home would
    // render inside a viewport that cannot scroll.
    // Exact name: the logo is also a link to "/" and is labelled "JLBC home".
    fireEvent.click(screen.getByRole("link", { name: /JLBC home/i }));

    expect(await screen.findByTestId("home")).toBeInTheDocument();
    expect(pinned()).toBe(false);
  });

  it("never pins on a page that is not AI Mode", async () => {
    mountAt("/");
    expect(await screen.findByTestId("home")).toBeInTheDocument();
    expect(pinned()).toBe(false);
  });

  it("un-pins on unmount, not just on route change", async () => {
    vi.spyOn(api, "aiStatus").mockResolvedValue(AI_STATUS);
    const view = render(
      <MemoryRouter>
        <Ai />
      </MemoryRouter>,
    );
    await screen.findByTestId("ai-panel");
    expect(pinned()).toBe(true);

    view.unmount();
    expect(pinned()).toBe(false);
  });
});

describe("the history rail's '+ New chat' always starts a fresh chat", () => {
  // Issue 2 (2026-08-03): pressing "+ New chat" from an ALREADY fresh chat
  // (selectedChatId null) used to be a key no-op — the conversation was keyed
  // on `${corpus}:new` and setting selectedChatId to null again changed
  // nothing, so the in-memory conversation never reset. The nonce in the key
  // fixes that. Auto-save needs no client code: the server persists every
  // completed turn to history at teardown, so nothing is lost on remount
  // (Destin, 2026-08-03 — no discard warning wanted).

  function sendAQuestion() {
    // Type into the composer and Send. The budget corpus's starter chips
    // render ONLY when turns.length === 0, so after a turn they are gone —
    // their reappearance after "+ New chat" is the signal the thread reset.
    const input = screen.getByPlaceholderText("Ask about the budget…");
    fireEvent.change(input, { target: { value: "how much did AHCCCS get?" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
  }

  it("resets a started-but-unsent conversation when '+ New chat' is pressed", async () => {
    mountAt("/ai");
    await screen.findByTestId("ai-panel");
    expect(await screen.findByTestId("ai-bottom-chrome")).toBeInTheDocument();
    // A fresh chat shows the starter chips.
    expect(
      screen.getByRole("button", { name: /FY2025 Aviation Fund balance/i }),
    ).toBeInTheDocument();

    // First "+ New chat" from a brand-new chat: the thread must stay fresh
    // (chips still present), and it must not throw.
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }));
    expect(await screen.findByTestId("ai-panel")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /FY2025 Aviation Fund balance/i }),
    ).toBeInTheDocument();

    // Start a conversation (send a question) — the starter chips disappear.
    sendAQuestion();
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /FY2025 Aviation Fund balance/i }),
      ).not.toBeInTheDocument(),
    );

    // NOW the bug: from this started-but-unsaved chat, "+ New chat" must
    // reset to a blank chat. With the fix it remounts and the starter chips
    // come back; without it the key is already "...:new" and they never do.
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /FY2025 Aviation Fund balance/i }),
      ).toBeInTheDocument(),
    );
  });

  it("resets even from an already-fresh chat — repeated '+ New chat' keeps working", async () => {
    mountAt("/ai");
    await screen.findByTestId("ai-panel");

    // Click twice from a brand-new chat. The first leaves it fresh; the
    // nonce means the SECOND also remounts (fresh → fresh → fresh), which the
    // old key scheme could not do. We assert it does not throw and the panel
    // is still present and fresh throughout.
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }));
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }));
    expect(await screen.findByTestId("ai-panel")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /FY2025 Aviation Fund balance/i }),
    ).toBeInTheDocument();
  });
});

describe("the pinning CSS stays scoped", () => {
  // jsdom applies no stylesheet and computes no layout, so no rendering test
  // can prove that Home still scrolls. Reading the stylesheet can: a rule that
  // stops the viewport scrolling is only safe if its selector is gated on the
  // AI page's own class.
  // Resolved from the vitest root (webapp/), not from import.meta.url — under
  // the jsdom environment import.meta.url is an http: URL, not a file: one.
  const css = readFileSync(resolve(process.cwd(), "src/styles/app.css"), "utf8");

  /** Split the sheet into `selector { declarations }` pairs, with comments
   *  stripped first so a commented-out rule cannot fail (or pass) the check. */
  function rules(): { selector: string; body: string }[] {
    const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
    const out: { selector: string; body: string }[] = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(stripped)) !== null) {
      out.push({ selector: m[1]!.trim(), body: m[2]! });
    }
    return out;
  }

  it("scopes every html/body overflow-hidden rule under the AI class", () => {
    const offenders = rules().filter(
      (r) =>
        /(^|[\s,>])(html|body)\b/.test(r.selector) &&
        /overflow(-y)?\s*:\s*hidden/.test(r.body) &&
        !r.selector.includes(PIN),
    );
    expect(offenders.map((r) => r.selector)).toEqual([]);
  });

  it("scopes every html/body viewport-height rule under the AI class", () => {
    // `height:100dvh` on <body> is the other half of the pin: it is what makes
    // the document exactly one screen tall. Unscoped, it would truncate every
    // other page at one screen with the overflow clipped away.
    const offenders = rules().filter(
      (r) =>
        /(^|[\s,>])(html|body)\b/.test(r.selector) &&
        /height\s*:\s*100(d|s|l)?vh/.test(r.body) &&
        !r.selector.includes(PIN),
    );
    expect(offenders.map((r) => r.selector)).toEqual([]);
  });
});
