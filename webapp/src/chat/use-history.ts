import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api";

// The history rail's data hook: loads on mount, debounces search, and
// exposes rename/remove as optimistic local mutations.
//
// Two things the tests above will not catch on their own:
//  - Drop a stale response: with a 200 ms debounce, a fast typist can have
//    two searches in flight; the slower one must not overwrite the newer
//    result. A request sequence number ignores any answer that is not the
//    latest.
//  - remove is optimistic — put the row back if the DELETE fails. A chat
//    that vanishes from the rail and is still on disk is worse than an
//    error.

const DEBOUNCE_MS = 200;

export function useHistory() {
  const [chats, setChats] = useState<api.HistoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  // Sequence number so a slow in-flight response cannot overwrite a newer
  // one. Every fetch increments it and captures its own number; when the
  // response comes back, if the number is stale we drop it.
  const seqRef = useRef(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Whether a non-empty search is active. This — NOT the seq counter — is the
  // right signal for "clearing the box should restore the full list": the seq
  // counter is bumped by the mount fetch too, so gating on it re-fires a
  // redundant list load on mount and (worse) would stop restoring the list
  // the day the initial load ever stopped bumping it. Gate on the actual
  // search state instead.
  const searchedRef = useRef(false);

  const fetchList = useCallback(async () => {
    const seq = ++seqRef.current;
    setLoading(true);
    setError(null);
    try {
      const { conversations } = await api.listHistory();
      if (seq !== seqRef.current) return; // stale
      setChats(conversations);
    } catch (err) {
      if (seq !== seqRef.current) return;
      setError(err instanceof Error ? err.message : "Could not load chat history");
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, []);

  const fetchSearch = useCallback(async (q: string) => {
    const seq = ++seqRef.current;
    setLoading(true);
    setError(null);
    try {
      const { results } = await api.searchHistory(q);
      if (seq !== seqRef.current) return; // stale
      setChats(results);
    } catch (err) {
      if (seq !== seqRef.current) return;
      setError(err instanceof Error ? err.message : "Could not search chat history");
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, []);

  // Load on mount.
  useEffect(() => {
    fetchList();
  }, [fetchList]);

  // Debounced search: when the trimmed query changes, wait DEBOUNCE_MS then
  // either search or fall back to the full list.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const trimmed = query.trim();
    if (!trimmed) {
      // Empty query restores the full list — but only if a search was active
      // (otherwise this is the initial mount and the fetchList above already
      // handled it). Tracked by searchedRef, not the seq counter: see its
      // declaration for why the counter is the wrong signal here.
      if (searchedRef.current) {
        searchedRef.current = false;
        debounceRef.current = setTimeout(() => fetchList(), DEBOUNCE_MS);
      }
    } else {
      searchedRef.current = true;
      debounceRef.current = setTimeout(() => fetchSearch(trimmed), DEBOUNCE_MS);
    }
    // ONE cleanup covering BOTH branches. It used to hang off the search
    // branch only, so clearing the search box scheduled a fetch with no way
    // to cancel it — and the rail unmounts on every chat switch (Ai.tsx keys
    // AiConversation), well inside the 200 ms window. The timer then fired an
    // unnecessary request and called setState on a dead hook.
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, fetchList, fetchSearch]);

  const reload = useCallback(() => {
    fetchList();
  }, [fetchList]);

  const rename = useCallback(async (id: string, title: string) => {
    try {
      const updated = await api.renameHistoryChat(id, title);
      setChats((prev) => prev.map((c) => (c.id === id ? { ...c, ...updated } : c)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not rename chat");
    }
  }, []);

  // Returns whether the chat is really gone. The caller needs to know:
  // deleting the OPEN chat has to deselect it, and doing that after a FAILED
  // delete would throw away the analyst's view of a chat that still exists.
  const remove = useCallback(async (id: string): Promise<boolean> => {
    // Optimistic: remove locally first, put back if the DELETE fails.
    let removed: api.HistoryRow | undefined;
    setChats((prev) => {
      removed = prev.find((c) => c.id === id);
      return prev.filter((c) => c.id !== id);
    });
    try {
      await api.deleteHistoryChat(id);
      return true;
    } catch (err) {
      // Put the row back — a chat that vanishes and is still on disk is
      // worse than an error.
      if (removed) {
        setChats((prev) => {
          if (prev.some((c) => c.id === id)) return prev;
          return [...prev, removed!].sort(
            (a, b) => (b.updated_at > a.updated_at ? 1 : -1),
          );
        });
      }
      setError(err instanceof Error ? err.message : "Could not delete chat");
      return false;
    }
  }, []);

  return { chats, loading, error, query, setQuery, reload, rename, remove };
}
