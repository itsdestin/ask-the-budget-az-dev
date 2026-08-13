import {
  adminAliases,
  adminGuidance,
  issues,
  saveAdminAliases,
  saveAdminGuidance,
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
