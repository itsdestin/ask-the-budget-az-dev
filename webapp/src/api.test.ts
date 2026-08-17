import {
  adminAliases,
  adminGuidance,
  bookFormats,
  checkBookFormatUrl,
  issues,
  saveAdminAliases,
  saveAdminGuidance,
  saveBookFormat,
  search,
  submitIssue,
  updateIssue,
} from "./api";

// WHY these two tests exist: TypeScript checks the ARGUMENTS of search(), but
// nothing checks the JSON that actually goes over the wire against the frozen
// backend contract (app/routes/search.py's SearchBody). A typo like `q:` for
// `query:` — or an extra key FastAPI would reject — typechecks fine and only
// fails at runtime. So pin the serialized body, and pin that a backend error
// `detail` reaches the caller instead of being flattened to a status code.

function okJson(body: unknown) {
  return vi.fn().mockResolvedValue({ ok: true, json: async () => body });
}

afterEach(() => vi.unstubAllGlobals());

test("POSTs exactly {query, filters, corpus} to /api/search", async () => {
  const fetchMock = okJson({ results: [], total: 0, provider: "stub" });
  vi.stubGlobal("fetch", fetchMock);

  await search("roads", { publisher: ["jlbc"] }, "budget");

  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/search");
  expect(init.method).toBe("POST");
  // toEqual (not objectContaining): an EXTRA key is a contract break too.
  expect(JSON.parse(init.body as string)).toEqual({
    query: "roads",
    filters: { publisher: ["jlbc"] },
    corpus: "budget",
  });
});

test("surfaces the backend's error detail in the thrown Error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: "query is empty" }),
    }),
  );

  await expect(search("")).rejects.toThrow("query is empty");
});

// One failure-path spec per new function — same "surfaces the backend's
// error detail" shape as the search() test above, applied to each new
// route so a broken `fail()` call site doesn't silently flatten to a
// generic status-code message.

function failJson(status: number, detail: string) {
  return vi.fn().mockResolvedValue({ ok: false, status, json: async () => ({ detail }) });
}

test("adminAliases surfaces the backend's error detail", async () => {
  vi.stubGlobal("fetch", failJson(403, "admin only"));
  await expect(adminAliases()).rejects.toThrow("admin only");
});

test("saveAdminAliases surfaces the backend's error detail", async () => {
  vi.stubGlobal("fetch", failJson(400, "'for' is an everyday word"));
  await expect(saveAdminAliases({ added: [], disabled: [] })).rejects.toThrow(
    "'for' is an everyday word",
  );
});

test("adminGuidance surfaces the backend's error detail", async () => {
  vi.stubGlobal("fetch", failJson(403, "admin only"));
  await expect(adminGuidance()).rejects.toThrow("admin only");
});

test("saveAdminGuidance surfaces the backend's error detail", async () => {
  vi.stubGlobal("fetch", failJson(400, "over the 8,192 byte limit"));
  await expect(saveAdminGuidance("too long")).rejects.toThrow("over the 8,192 byte limit");
});

test("issues surfaces the backend's error detail", async () => {
  vi.stubGlobal("fetch", failJson(500, "share unavailable"));
  await expect(issues()).rejects.toThrow("share unavailable");
});

test("submitIssue surfaces the backend's error detail", async () => {
  vi.stubGlobal("fetch", failJson(400, "Describe what went wrong"));
  await expect(submitIssue({ description: "" })).rejects.toThrow("Describe what went wrong");
});

test("updateIssue surfaces the backend's error detail", async () => {
  vi.stubGlobal("fetch", failJson(404, "No such report"));
  await expect(updateIssue("abc", { status: "resolved" })).rejects.toThrow("No such report");
});

// --- whole-report links -----------------------------------------------------
//
// WHY these six exist: the row's own suite
// (`pages/upload/ReportLinkRow.test.tsx`, which replaced the deleted
// `admin/ReportLinksPanel.test.tsx` when the panel moved onto the book card)
// mocks all three of these functions outright, so NOTHING was checking what
// goes over the wire. Both of these mutations left the whole suite green
// before they were written:
//
//   * typo the PUT path to `/api/admin/book-format-TYPO`
//   * replace `fail(r, "saving the whole-report links")` with a bare
//     `throw new Error("Request failed")`
//
// The first means every approval fails against the real server with the suite
// still green. The second silently deletes the store's own refusal sentence,
// which spec R10 and `write_edition`'s docstring both require to reach the
// admin VERBATIM — and the panel spec that looks like it covers that is
// asserting against a hand-written `mockRejectedValue` string, never against
// `fail()`. The `fiscal_year` / `single_file` / `linked_toc` body keys are
// pinned for the same reason: FastAPI's `EditionWrite` rejects a renamed key,
// and TypeScript cannot see across the wire.

test("bookFormats GETs /api/admin/book-formats, and skips the cache only when asked", async () => {
  const fetchMock = okJson({
    pending: [],
    approved: [],
    online: true,
    reason: null,
    problems: [],
  });
  vi.stubGlobal("fetch", fetchMock);

  await bookFormats();
  expect(fetchMock.mock.calls[0][0]).toBe("/api/admin/book-formats");

  // "Look again" exists because an edition published an hour ago is otherwise
  // invisible for 12 hours. If this parameter stops being sent, the button
  // still appears to work and simply serves the cached answer forever.
  await bookFormats(true);
  expect(fetchMock.mock.calls[1][0]).toBe("/api/admin/book-formats?refresh=true");
});

test("bookFormats surfaces the backend's error detail", async () => {
  vi.stubGlobal("fetch", failJson(403, "admin only"));
  await expect(bookFormats()).rejects.toThrow("admin only");
});

test("saveBookFormat PUTs exactly {family, fiscal_year, single_file, linked_toc}", async () => {
  const fetchMock = okJson({
    ok: true,
    names_its_year: { single_file: true, linked_toc: null },
  });
  vi.stubGlobal("fetch", fetchMock);

  await saveBookFormat(
    "Appropriations Report",
    2028,
    "https://www.azjlbc.gov/28ar/fy2028approprpt.pdf",
    null,
  );

  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/admin/book-formats");
  expect(init.method).toBe("PUT");
  // toEqual (not objectContaining): an EXTRA key is a contract break too, and
  // `null` for "JLBC published no such format" must survive JSON.stringify
  // rather than being dropped the way `undefined` would be.
  expect(JSON.parse(init.body as string)).toEqual({
    family: "Appropriations Report",
    fiscal_year: 2028,
    single_file: "https://www.azjlbc.gov/28ar/fy2028approprpt.pdf",
    linked_toc: null,
  });
});

test("saveBookFormat surfaces the store's refusal verbatim", async () => {
  vi.stubGlobal(
    "fetch",
    failJson(400, "At least one of the two formats must have a link."),
  );
  await expect(saveBookFormat("Baseline", 2028, null, null)).rejects.toThrow(
    "At least one of the two formats must have a link.",
  );
});

test("checkBookFormatUrl POSTs exactly {url, fiscal_year} to the check route", async () => {
  const fetchMock = okJson({
    ok: true,
    status: 200,
    bytes: 123,
    names_its_year: true,
    reason: null,
  });
  vi.stubGlobal("fetch", fetchMock);

  await checkBookFormatUrl("https://www.azjlbc.gov/28ar/other.pdf", 2028);

  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/admin/book-formats/check");
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body as string)).toEqual({
    url: "https://www.azjlbc.gov/28ar/other.pdf",
    fiscal_year: 2028,
  });
});

test("checkBookFormatUrl surfaces the backend's error detail", async () => {
  vi.stubGlobal("fetch", failJson(403, "admin only"));
  await expect(checkBookFormatUrl("https://x.test/a.pdf", 2028)).rejects.toThrow(
    "admin only",
  );
});
