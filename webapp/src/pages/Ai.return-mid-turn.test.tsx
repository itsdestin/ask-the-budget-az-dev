// Coming BACK to /ai must show the conversation, not the availability gate.
//
// This is the scenario spec P4 exists to serve, end to end: start a turn, go
// read Budget Documents, come back. Hoisting the conversation above the router
// (chat/ai-session.tsx) made it SURVIVE that trip — but this page still
// unmounts and remounts, so its `useAiStatus()` probe restarted from nothing
// and the page rendered "Checking whether AI answers are available…" over the
// analyst's live answer for a round trip. In the tail case a hiccuped probe
// resolves to a real "unavailable" verdict and they read "AI Mode is currently
// unavailable" while a paid Deep Research turn streams invisibly behind it.
//
// Two fixes below, but NOT one spec each — read this before trusting the
// shape. `Ai.tsx` refuses to draw the gate over a conversation that already
// has turns (`hasConversation`), and that guard alone is enough to pass BOTH
// specs below, cache or no cache: a return trip with an answer already on
// screen never reaches the `probing || gated` branch in the first place. So
// neither spec here actually arms `use-ai-status.ts`'s verdict cache —
// `chat/__tests__/use-ai-status.test.ts` is what pins the cache directly
// (renderHook, resolve once, unmount, remount against a probe that never
// settles, assert the second mount is non-null on its FIRST render). Kept
// here anyway because these two specs are the end-to-end proof the two
// mechanisms combine correctly on the real page:
//   (a) `use-ai-status.ts` seeds from the last verdict this tab received, so a
//       return trip renders the previous answer immediately and re-probes
//       silently. The re-probe is deliberately kept — it is how the client
//       notices an administrator adding an API key without a reload.
//   (b) `Ai.tsx` refuses to draw the gate over a conversation that already has
//       turns. That covers what seeding cannot: a re-probe that genuinely
//       resolves to "unavailable".

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Ai } from "./Ai";
import * as api from "../api";
import { AiSessionProvider } from "../chat/ai-session";
import { AI_STATUS, stubConversationFetch, stubScrollIntoView } from "./ai-test-fixtures";

// The verdict cache reset moved to a global `beforeEach` in `test-setup.ts` —
// see that file for why (every spec file needing a cold tab used to have to
// remember this itself, and one file didn't).

// `stubConversationFetch` (below) uses `vi.stubGlobal`, which `restoreMocks:
// true` does NOT undo (that setting only resets `vi.fn`/`vi.spyOn` targets,
// not globals replaced wholesale). `Ai.test.tsx` already carries this same
// teardown; this file diverging from it is what let the gap sit unnoticed.
afterEach(() => vi.unstubAllGlobals());

function Nav() {
  const navigate = useNavigate();
  return (
    <>
      <button onClick={() => navigate("/search")}>go search</button>
      <button onClick={() => navigate("/ai")}>go ai</button>
    </>
  );
}

function mountApp() {
  return render(
    <MemoryRouter initialEntries={["/ai"]}>
      <AiSessionProvider>
        <Nav />
        <Routes>
          <Route path="/ai" element={<Ai />} />
          <Route path="/search" element={<div>budget documents page</div>} />
        </Routes>
      </AiSessionProvider>
    </MemoryRouter>,
  );
}

/** Ask a question the way the analyst does: type into the composer, Enter. */
async function ask(text: string) {
  const box = screen.getByRole("textbox");
  fireEvent.change(box, { target: { value: text } });
  await act(async () => {
    fireEvent.keyDown(box, { key: "Enter" });
  });
}

async function leaveAndReturn() {
  await act(async () => {
    screen.getByText("go search").click();
  });
  expect(screen.getByText("budget documents page")).toBeInTheDocument();
  await act(async () => {
    screen.getByText("go ai").click();
  });
}

describe("returning to /ai mid-conversation", () => {
  beforeEach(() => {
    stubScrollIntoView();
    stubConversationFetch();
  });

  it("shows the conversation, not the probing gate, while the re-probe is in flight", async () => {
    // The first probe answers; the SECOND one — fired by this page remounting
    // on the way back — never settles. Unfixed, that leaves `status === null`
    // and the page renders the gate over a live answer indefinitely.
    vi.spyOn(api, "aiStatus")
      .mockResolvedValueOnce(AI_STATUS)
      .mockReturnValue(new Promise<api.AiStatus>(() => {}));

    mountApp();
    await screen.findByRole("textbox");
    await ask("how much for ADC?");
    await waitFor(() => expect(screen.getByText(/AHCCCS receives/)).toBeInTheDocument());

    await leaveAndReturn();

    expect(screen.queryByTestId("ai-gate")).toBeNull();
    expect(screen.getByText(/AHCCCS receives/)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("keeps the conversation on screen even if the re-probe reports unavailable", async () => {
    // A gate is for a page that cannot do its job. A page holding an answer the
    // analyst is reading — and possibly a turn still streaming and billing — is
    // doing its job, whatever a fresh probe says.
    vi.spyOn(api, "aiStatus")
      .mockResolvedValueOnce(AI_STATUS)
      .mockResolvedValue({
        ...AI_STATUS,
        available: false,
        reason: "the app server could not be reached",
      });

    mountApp();
    await screen.findByRole("textbox");
    await ask("how much for ADC?");
    await waitFor(() => expect(screen.getByText(/AHCCCS receives/)).toBeInTheDocument());

    await leaveAndReturn();
    // Let the unavailable verdict land before asserting.
    await act(async () => {});

    expect(screen.queryByTestId("ai-gate")).toBeNull();
    expect(screen.queryByText(/currently unavailable/i)).toBeNull();
    expect(screen.getByText(/AHCCCS receives/)).toBeInTheDocument();
  });
});
