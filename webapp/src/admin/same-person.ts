// The ONE client-side "are these two usernames the same person" check
// (spec U0). Mirrors `users.whoami.same_person` (Python:
// `a.strip().casefold() == b.strip().casefold()`, blank never matches
// blank).
//
// JavaScript has no `casefold` — `toLowerCase()` is the nearest available
// approximation, and it agrees with `casefold()` for the ASCII characters
// a Windows account name actually contains (it only diverges on things
// like German ß or dotted İ, which do not appear in `%USERNAME%`). The
// SERVER is the authority on identity (`users/whoami.py`); every call site
// here is shaping a DRAFT or a picker before a save, never a security or
// correctness boundary — a save round-trips through the server's own fold
// regardless of what this function decided.
//
// Found missing in the 2026-08-25 final review: `PeoplePanel.tsx`'s
// hide/unhide and `Admin.tsx`'s `setPersonLimit` each carried their own
// exact or `toLowerCase()` comparison, so a person re-spelled by Windows
// between visits (`DMOSS` → `dmoss`) could be hidden under one spelling
// and reappear under the next. One function, one place to fix it.
export function samePerson(a: string, b: string): boolean {
  const fa = a.trim().toLowerCase();
  if (!fa) return false;
  return fa === b.trim().toLowerCase();
}
