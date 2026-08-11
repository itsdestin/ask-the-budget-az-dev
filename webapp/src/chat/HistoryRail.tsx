// The collapsible history rail: list, search, rename, delete.
//
// Mounts to the LEFT of the chat region in AiModePanel. Owns no state beyond
// what useHistory provides; the active chat id and the select/new-chat
// callbacks are props, so the page (Ai.tsx) stays the single source of truth
// for which chat is open.

import { useEffect, useMemo, useState } from "react";
import { useHistory } from "./use-history.js";

/** The current conversation's stand-in id, before the server has minted a
 *  real one. A brand-new chat has NO id until the first send — `useChat`
 *  creates the conversation lazily — so the rail needs something to key the
 *  placeholder on. Never sent to the server, never compared to a stored id. */
export const DRAFT_CHAT_ID = "draft";

interface HistoryRailProps {
  activeId: string | null;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  collapsed: boolean;
  onToggle: () => void;
  /** Called after a chat is deleted. The page owns `selectedChatId`, and a
   *  chat deleted while it is the OPEN one has to be deselected — otherwise
   *  the thread keeps rendering a transcript that no longer exists and
   *  `useChat` keeps trying to resume it. */
  onDeleted?: (id: string) => void;
  /** Bumped by the panel when a turn ends. `useHistory` only fetches on
   *  mount, so a brand-new chat and the title the server generates for it a
   *  few seconds later never appeared in the rail until something remounted
   *  it. Any change to this value re-reads the list. */
  reloadToken?: number;
  /** The current conversation, when it has NOT been persisted yet — either
   *  the DRAFT_CHAT_ID sentinel or a live server id whose transcript has not
   *  been written. Non-null only for a NEW chat: a chat opened from the rail
   *  already has a row on the way, and treating it as a draft would flash a
   *  "New chat" placeholder over it while the list loads. */
  draftId?: string | null;
}

// Group chats by day: Today / Yesterday / Earlier.
function dayLabel(updatedAt: string): string {
  const now = new Date();
  const updated = new Date(updatedAt);
  if (isNaN(updated.getTime())) return "Earlier";
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart.getTime() - 86400000);
  if (updated >= todayStart) return "Today";
  if (updated >= yesterdayStart) return "Yesterday";
  return "Earlier";
}

// Every chat STORE row has a title field, but it can be an empty string:
// auto-naming (harness/titles.py) runs only after the first completed
// exchange and falls back to truncation on any failure, so a chat that
// never got a generated title (or whose naming call failed) persists with
// title="". Rendering that as-is left a blank strip beside the rename/delete
// buttons — a ghost row that looked like a rendering bug. A fallback label
// means every stored chat reads as a row, and gives the rename/delete
// actions something to sit next to. (This is a DISPLAY default only; the
// stored title field is never mutated here.)
function displayTitle(title: string): string {
  const trimmed = (title || "").trim();
  return trimmed ? trimmed : "Untitled chat";
}

interface Group {
  label: string;
  chats: ReturnType<typeof useHistory>["chats"];
}

function groupChats(chats: ReturnType<typeof useHistory>["chats"]): Group[] {
  const order = ["Today", "Yesterday", "Earlier"];
  const map = new Map<string, Group>();
  for (const chat of chats) {
    const label = dayLabel(chat.updated_at);
    if (!map.has(label)) map.set(label, { label, chats: [] });
    map.get(label)!.chats.push(chat);
  }
  return order
    .filter((label) => map.has(label))
    .map((label) => map.get(label)!);
}

export function HistoryRail({
  activeId,
  onSelect,
  onNewChat,
  collapsed,
  onToggle,
  onDeleted,
  reloadToken = 0,
  draftId = null,
}: HistoryRailProps) {
  const { chats, loading, error, query, setQuery, reload, rename, remove } = useHistory();
  // Track which chat's title is being edited inline.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  // Which chat's delete button is armed. Deletion is permanent — H6 gives
  // history no expiry and no undo — and the ✕ sits directly beside the ✎, so
  // a single mis-click used to destroy a transcript outright. Two clicks, no
  // modal: the second click is the confirmation.
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  // Re-read the list whenever the panel says a turn ended. Skips the initial
  // value so this never duplicates useHistory's own mount fetch.
  useEffect(() => {
    if (reloadToken > 0) reload();
  }, [reloadToken, reload]);

  const searching = query.trim().length > 0;
  // The placeholder shows while the current NEW conversation has no row of
  // its own — either it has no server id yet, or it has one and the turn that
  // would write its transcript has not finished. Matching on IDENTITY rather
  // than on "a turn completed" means there is never a moment with two rows or
  // with none: when the real row arrives carrying the same id, this predicate
  // simply goes false. Hidden while searching — a search filters what is
  // stored, and the draft is not.
  const showPlaceholder =
    !searching && draftId != null && !chats.some((c) => c.id === draftId);

  // Computed unconditionally, ABOVE the `collapsed` early return below: a
  // hook called only on some renders (collapsed toggles at runtime, driven by
  // AiModePanel's own state) violates the Rules of Hooks and previously threw
  // "Rendered fewer hooks than expected" the moment collapse state changed —
  // caught by the existing ai-mode-panel-source suite, not by this file's own
  // tests, none of which toggle `collapsed`.
  const groups = useMemo(() => {
    const base = groupChats(chats);
    if (!showPlaceholder || draftId == null) return base;
    const placeholder = {
      id: draftId,
      title: "New chat",
      // Unused by this component's rendering; present to satisfy HistoryRow.
      corpus: "budget",
      created_at: "",
      updated_at: "",
      title_is_manual: false,
      message_count: 0,
    } as ReturnType<typeof useHistory>["chats"][number];
    // Inserted AFTER grouping rather than given a fake timestamp and grouped:
    // a synthetic `updated_at` of "now" would be recomputed on every render
    // and is a lie in the data rather than a decision in the view.
    const today = base.find((g) => g.label === "Today");
    if (!today) return [{ label: "Today", chats: [placeholder] }, ...base];
    return base.map((g) =>
      g === today ? { ...g, chats: [placeholder, ...g.chats] } : g,
    );
  }, [chats, showPlaceholder, draftId]);

  // Collapse is a prop, owned by AiModePanel — but the collapsed preference
  // persists per device in localStorage, and AiModePanel reads it on mount.
  // The auto-collapse-when-source-opens effect lives in AiModePanel, not here.

  if (collapsed) {
    return (
      <nav className="history-rail is-collapsed" aria-label="Chat history">
        <button
          type="button"
          className="history-rail-toggle"
          aria-label="Chat history"
          onClick={onToggle}
          title="Show chat history"
        >
          {/* A simple collapsed glyph — expand arrow */}
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round"
               strokeLinejoin="round" aria-hidden="true">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </button>
      </nav>
    );
  }

  return (
    <nav className="history-rail" aria-label="Chat history">
      <div className="history-rail-head">
        <button
          type="button"
          className="history-rail-new"
          onClick={onNewChat}
        >
          + New chat
        </button>
        <button
          type="button"
          className="history-rail-collapse"
          aria-label="Collapse chat history"
          onClick={onToggle}
          title="Hide chat history"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round"
               strokeLinejoin="round" aria-hidden="true">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
      </div>

      <input
        className="history-rail-search"
        type="search"
        placeholder="Search chats…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Search chat history"
      />

      {error && (
        <p className="history-rail-error" role="alert">{error}</p>
      )}

      {/* !showPlaceholder guards both branches below: on a genuinely fresh
          install chats.length is 0 while showPlaceholder is true (the new
          chat has no stored row yet), and without this gate the "Loading…" /
          "No saved chats yet" message would win over the placeholder — the
          one case this whole feature exists for would render as if it never
          fired. */}
      {loading && !showPlaceholder && chats.length === 0 ? (
        <p className="history-rail-empty">Loading…</p>
      ) : !showPlaceholder && chats.length === 0 ? (
        <p className="history-rail-empty">
          {searching
            ? "No chats match your search."
            : "No saved chats yet — ask a question to start."}
        </p>
      ) : (
        <div className="history-rail-list">
          {groups.map((group) => (
            <div key={group.label} className="history-rail-group">
              <h3 className="history-rail-group-label">{group.label}</h3>
              {group.chats.map((chat) => (
                <div
                  key={chat.id}
                  className={
                    "history-rail-item" +
                    (chat.id === activeId ? " is-active" : "")
                  }
                >
                  {showPlaceholder && chat.id === draftId ? (
                    // showPlaceholder, not just an id match: once the REAL row
                    // lands it carries this same id (that is the P2 identity
                    // rule), and by then showPlaceholder is false — so this
                    // branch must not also catch the real row and render it
                    // as "New chat" with no rename/delete.
                    //
                    // No button: there is nothing to select (it is already the
                    // current chat) and nothing to open. No rename or delete
                    // either — both address a file that does not exist.
                    <span className="history-rail-chat history-rail-chat-static">
                      <span className="history-rail-chat-title">New chat</span>
                    </span>
                  ) : (
                    <>
                      {editingId === chat.id ? (
                        <input
                          className="history-rail-rename"
                          type="text"
                          value={editValue}
                          autoFocus
                          onChange={(e) => setEditValue(e.target.value)}
                          onBlur={() => {
                            const trimmed = editValue.trim();
                            if (trimmed && trimmed !== chat.title) {
                              void rename(chat.id, trimmed);
                            }
                            setEditingId(null);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              (e.target as HTMLInputElement).blur();
                            } else if (e.key === "Escape") {
                              setEditingId(null);
                            }
                          }}
                        />
                      ) : (
                        <button
                          type="button"
                          className="history-rail-chat"
                          onClick={() => onSelect(chat.id)}
                          title={chat.title}
                        >
                          <span className="history-rail-chat-title">{displayTitle(chat.title)}</span>
                          {chat.snippet && (
                            <span className="history-rail-chat-snippet">
                              {chat.snippet}
                            </span>
                          )}
                        </button>
                      )}
                      {editingId !== chat.id && (
                        <div className="history-rail-actions">
                          <button
                            type="button"
                            className="history-rail-action"
                            aria-label="Rename chat"
                            title="Rename"
                            onClick={() => {
                              setConfirmingId(null);
                              setEditingId(chat.id);
                              // Use the display fallback so the rename box opens
                              // with a visible default to edit, not a blank input
                              // that looks broken (and would save empty on blur).
                              setEditValue(displayTitle(chat.title));
                            }}
                          >
                            ✎
                          </button>
                          {confirmingId === chat.id ? (
                            <button
                              type="button"
                              className="history-rail-action is-confirming"
                              aria-label="Confirm delete chat"
                              title="This cannot be undone — click to delete"
                              onBlur={() => setConfirmingId(null)}
                              onClick={() => {
                                setConfirmingId(null);
                                // Only on a real delete — a failed DELETE restores
                                // the row, and deselecting then would discard the
                                // analyst's view of a chat that still exists.
                                void remove(chat.id).then((gone) => {
                                  if (gone) onDeleted?.(chat.id);
                                });
                              }}
                            >
                              Delete?
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="history-rail-action"
                              aria-label="Delete chat"
                              title="Delete"
                              onClick={() => setConfirmingId(chat.id)}
                            >
                              ✕
                            </button>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </nav>
  );
}
