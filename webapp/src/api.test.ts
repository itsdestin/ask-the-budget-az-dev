import { search } from "./api";

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
