// The `/vitest` subpath (not the bare import) is jest-dom's vitest entry: it
// extends vitest's `expect` AND ships the matcher type augmentation, so
// `expect(el).toBeInTheDocument()` typechecks under `tsc -b`.
import "@testing-library/jest-dom/vitest";
