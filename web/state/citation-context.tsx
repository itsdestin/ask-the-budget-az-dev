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

import type { Citation } from "@/lib/citation-extract";

export type CitationHandler = (citation: Citation) => void;

export interface CitationBus {
  /** Notify all subscribers of a click on a specific citation. */
  select(citation: Citation): void;
  /** Subscribe to selections; returns an unsubscribe function. */
  subscribe(handler: CitationHandler): () => void;
}

const CitationBusContext = createContext<CitationBus | null>(null);

export function CitationBusProvider({ children }: { children: ReactNode }) {
  // Set, not array, so duplicate subscriptions are de-duped
  // automatically (React StrictMode mounts effects twice in dev —
  // that's the most common source of accidental double-subscribe).
  const handlersRef = useRef<Set<CitationHandler>>(new Set());

  const select = useCallback((citation: Citation) => {
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
    return () => {
      handlersRef.current.delete(handler);
    };
  }, []);

  const bus = useMemo<CitationBus>(
    () => ({ select, subscribe }),
    [select, subscribe],
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
