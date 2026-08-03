// The collapsible history rail: list, search, rename, delete.
//
// Mounts to the LEFT of the chat region in AiModePanel. Owns no state beyond
// what useHistory provides; the active chat id and the select/new-chat
// callbacks are props, so the page (Ai.tsx) stays the single source of truth
// for which chat is open.

import { useState } from "react";
import { useHistory } from "./use-history.js";

interface HistoryRailProps {
  activeId: string | null;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  collapsed: boolean;
  onToggle: () => void;
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
}: HistoryRailProps) {
  const { chats, loading, error, query, setQuery, rename, remove } = useHistory();
  // Track which chat's title is being edited inline.
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

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

  const groups = groupChats(chats);
  const searching = query.trim().length > 0;

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

      {loading && chats.length === 0 ? (
        <p className="history-rail-empty">Loading…</p>
      ) : chats.length === 0 ? (
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
                          setEditingId(chat.id);
                          // Use the display fallback so the rename box opens
                          // with a visible default to edit, not a blank input
                          // that looks broken (and would save empty on blur).
                          setEditValue(displayTitle(chat.title));
                        }}
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        className="history-rail-action"
                        aria-label="Delete chat"
                        title="Delete"
                        onClick={() => void remove(chat.id)}
                      >
                        ✕
                      </button>
                    </div>
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
