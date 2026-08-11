"use client";

// Lightweight pub/sub for citation chip clicks. The chat side calls
// `bus.select(citation)`; viewers (PdfViewer in Phase 1c WS4c, future
// DocxViewer in Phase 2) call `bus.subscribe(handler)` to scroll +
// highlight. Lives in React Context rather than a global so tests
// and stories can inject a fake bus without monkey-patching.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";

import type { Citation } from "./citation-extract";

export type CitationHandler = (citation: Citation) => void;

/** A verdict the viewer publishes when it checks whether a citation's source
 *  still resolves. The chip subscribes and marks itself accordingly.
 *  `gone` = chunk 404; `moved` = chunk exists but the cited span is no longer
 *  in it (document was re-ingested); `resolved` = a re-check succeeded, so a
 *  chip that was marked stale (e.g. by a transient 404 during an ingest
 *  rewrite) clears itself. "We cannot tell" (503, network error) publishes
 *  nothing — it neither marks nor clears. */
export type UnresolvableReason = "gone" | "moved" | "resolved";

export type UnresolvableHandler = (chunkId: string, reason: UnresolvableReason) => void;

export interface CitationBus {
  /** Notify all subscribers of a click on a specific citation. */
  select(citation: Citation): void;
  /** Subscribe to selections; returns an unsubscribe function. */
  subscribe(handler: CitationHandler): () => void;
  /** Publish the outcome of a click-time source check. `gone`/`moved` mark
   *  the matching chip stale; `resolved` clears a stale mark. The chip with
   *  the matching chunkId updates itself. */
  markUnresolvable(chunkId: string, reason: UnresolvableReason): void;
  /** Subscribe to unresolvable verdicts; returns an unsubscribe function. */
  subscribeUnresolvable(handler: UnresolvableHandler): () => void;
}

const CitationBusContext = createContext<CitationBus | null>(null);

export function CitationBusProvider({ children }: { children: ReactNode }) {
  // Set, not array, so duplicate subscriptions are de-duped
  // automatically (React StrictMode mounts effects twice in dev —
  // that's the most common source of accidental double-subscribe).
  const handlersRef = useRef<Set<CitationHandler>>(new Set());
  // H5: subscribers for unresolvable verdicts (the chip marks itself).
  const unresolvableHandlersRef = useRef<Set<UnresolvableHandler>>(new Set());
  // The most recent selection, kept so a viewer that mounts BECAUSE of a
  // click still receives that click. Without this the first chip click
  // opened an empty source panel and the analyst had to click twice —
  // the subscriber's useEffect can only run after the mount that the
  // select() itself triggered, so by the time it subscribes the live
  // broadcast has already passed it by.
  const lastRef = useRef<Citation | null>(null);

  const select = useCallback((citation: Citation) => {
    lastRef.current = citation;
    for (const h of handlersRef.current) {
      try {
        h(citation);
      } catch (err) {
        // Don't let one buggy subscriber stop the others. Surface to
        // console for the dev loop; production builds drop it.
        console.error("[citation-bus] subscriber threw:", err);
      }
    }
  }, []);

  const subscribe = useCallback((handler: CitationHandler) => {
    handlersRef.current.add(handler);
    if (lastRef.current !== null) {
      // Replay is synchronous and one-shot, delivered only to the newly
      // subscribing handler — existing subscribers already saw the live
      // event and must not see it twice. StrictMode's double-mounted
      // effect subscribes (and is thus replayed to) twice, but both
      // deliveries carry the same citation into a setState, which is
      // idempotent, so no de-dup guard is needed here.
      try {
        handler(lastRef.current);
      } catch (err) {
        console.error("[citation-bus] subscriber threw on replay:", err);
      }
    }
    return () => {
      handlersRef.current.delete(handler);
    };
  }, []);

  const markUnresolvable = useCallback((chunkId: string, reason: UnresolvableReason) => {
    for (const h of unresolvableHandlersRef.current) {
      try {
        h(chunkId, reason);
      } catch (err) {
        console.error("[citation-bus] unresolvable subscriber threw:", err);
      }
    }
  }, []);

  const subscribeUnresolvable = useCallback((handler: UnresolvableHandler) => {
    unresolvableHandlersRef.current.add(handler);
    return () => {
      unresolvableHandlersRef.current.delete(handler);
    };
  }, []);

  const bus = useMemo<CitationBus>(
    () => ({ select, subscribe, markUnresolvable, subscribeUnresolvable }),
    [select, subscribe, markUnresolvable, subscribeUnresolvable],
  );

  return (
    <CitationBusContext.Provider value={bus}>
      {children}
    </CitationBusContext.Provider>
  );
}

/** Read the bus from context. Falling outside a provider returns a
 *  no-op bus rather than throwing — keeps non-chat surfaces (e.g.
 *  the empty state, error banner) from crashing. */
export function useCitationBus(): CitationBus {
  const ctx = useContext(CitationBusContext);
  return ctx ?? NOOP_BUS;
}

const NOOP_BUS: CitationBus = {
  select: () => {},
  subscribe: () => () => {},
  markUnresolvable: () => {},
  subscribeUnresolvable: () => () => {},
};

/** Subscribe to citation selections from inside a component. The
 *  handler is wrapped in a ref so callers can write inline arrow
 *  functions without re-subscribing on every render. */
export function useCitationSelected(handler: CitationHandler): void {
  const bus = useCitationBus();
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  useEffect(() => {
    return bus.subscribe((c) => handlerRef.current(c));
  }, [bus]);
}

/** Subscribe to unresolvable-citation verdicts from the viewer. The chip
 *  uses this to mark itself when its source no longer resolves (H5). */
export function useUnresolvable(handler: UnresolvableHandler): void {
  const bus = useCitationBus();
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  useEffect(() => {
    return bus.subscribeUnresolvable((id, reason) => handlerRef.current(id, reason));
  }, [bus]);
}
