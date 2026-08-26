import { joinChanges } from "./changes";

// The save control. Exists ONLY while there is something to save.
//
// It replaced a "Save changes" button parked between the AI Mode card and the
// Documents card (2026-07-31, Destin: "completely unclear which menu it
// attaches to and what needs to be saved"). Both halves of that were fair:
//
//  * It sat in the gap between two panels, so it read as belonging to
//    whichever one you happened to be looking at — including Documents,
//    which it had nothing to do with.
//  * It was always there, always identical, whether you had changed one
//    dropdown or nothing at all.
//
// So: no button at rest, and when there IS something pending, the bar says
// what it is. It sticks to the bottom of the viewport rather than living at
// one point in the page, which is what makes "which menu does this belong
// to" stop being a question — the answer is "the changes you just made",
// and it lists them.

export function SaveBar({
  changes,
  onSave,
  onDiscard,
  saving,
  error,
}: {
  changes: string[];
  onSave: () => void;
  onDiscard: () => void;
  saving: boolean;
  error: string | null;
}) {
  if (changes.length === 0 && !error) return null;

  return (
    <div className="adm-savebar" role="region" aria-label="Unsaved changes" data-testid="admin-savebar">
      <div className="adm-savebar-inner">
        <div className="adm-savebar-text">
          {changes.length > 0 ? (
            <>
              <strong>
                {changes.length === 1 ? "1 unsaved change" : `${changes.length} unsaved changes`}
              </strong>
              <span className="adm-savebar-list" data-testid="admin-savebar-list">
                {joinChanges(changes)}
              </span>
            </>
          ) : null}
          {error ? (
            <span className="adm-savebar-error" role="alert" data-testid="admin-save-error">
              {error}
            </span>
          ) : null}
        </div>
        <div className="adm-savebar-actions">
          <button
            type="button"
            className="adm-btn adm-btn-quiet adm-btn-sm"
            onClick={onDiscard}
            disabled={saving || changes.length === 0}
          >
            Discard
          </button>
          <button
            type="button"
            className="adm-btn"
            onClick={onSave}
            disabled={saving || changes.length === 0}
            data-testid="admin-save"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
