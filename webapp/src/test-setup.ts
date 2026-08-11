// The `/vitest` subpath (not the bare import) is jest-dom's vitest entry: it
// extends vitest's `expect` AND ships the matcher type augmentation, so
// `expect(el).toBeInTheDocument()` typechecks under `tsc -b`.
import "@testing-library/jest-dom/vitest";

import { beforeEach } from "vitest";

import { __resetAiStatusCache } from "./chat/use-ai-status";

// `use-ai-status.ts`'s verdict cache is MODULE-LEVEL (one per browser tab, by
// design — see that file's comment). vitest's `isolate: true` gives each test
// FILE a fresh module registry, so the cache does not leak across files on
// its own, but nothing resets it between tests WITHIN a file — and it used to
// be each file's own job to remember to. `Home.ai-mode.test.tsx` never did:
// its 3 specs ran in one file, so its 2nd and 3rd specs silently started from
// the 1st spec's cached "available" verdict rather than a cold probe, and
// only stayed green because every assertion there is `waitFor`-wrapped and
// tolerant of an already-settled value. `vite.config.ts`'s own comment on
// `restoreMocks: true` makes exactly this argument about order-dependent
// state leaking between tests in one file — this is the same class of bug,
// for a piece of state `restoreMocks` cannot see (a plain module variable,
// not a vi.fn()). One global reset here removes the need for every future
// spec file to know this cache exists at all.
beforeEach(() => __resetAiStatusCache());
