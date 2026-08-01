import { useCallback, useEffect, useId, useRef, useState } from "react";
import * as api from "../api";

// The model picker: a closed dropdown that opens into a rich menu.
//
// It has been through both extremes. A bare <select> looked unfinished next
// to the cards and switches, and hid the comparison the decision turns on. A
// full radio list fixed the comparison but put eight always-visible rows on
// the page, which is more weight than a setting an admin touches twice a year
// deserves (Destin, 2026-07-31: "takes up too much space… feels
// overwhelming").
//
// So: one row at rest, showing the current choice and what it costs. The
// comparison is one click away, and the menu is where the detail lives.
//
// A native <select> cannot do this — its options are text-only, so the chips
// and blurbs are impossible. That means implementing the listbox pattern by
// hand, which is why the keyboard handling below is deliberate rather than
// incidental: Arrow keys move, Enter/Space choose, Escape closes and returns
// focus, Tab closes, Home/End jump, and disabled rows are skipped rather than
// landed on. A custom control that a keyboard cannot drive is a regression
// from the <select> it replaced.

/** Cost of one question, in money a person reads.
 *
 *  Cents, not `$0.0127`. An admin comparing "half a cent" with "56 cents"
 *  gets the 100× difference immediately; comparing 0.0049 with 0.5625 means
 *  counting decimal places. */
export function perQuestion(usd: number | null): string | null {
  if (usd === null) return null;
  if (usd >= 1) return `about $${usd.toFixed(2)} a question`;
  const cents = usd * 100;
  if (cents < 0.5) return "under half a cent a question";
  if (cents < 1) return "about half a cent a question";
  return `about ${Math.round(cents)}¢ a question`;
}

/** How capable the model is, as a percentage plus a bar.
 *
 *  The percentage is computed server-side (`harness/catalog.py`) from
 *  Artificial Analysis's Intelligence Index against a fixed ceiling. A bare
 *  "57" means nothing to a non-technical admin — 57 out of what? — whereas
 *  85% carries its own reference point, and the bar and the number now say
 *  the same thing instead of the bar being a coincidence.
 *
 *  Nothing reaches 100%: the ceiling sits above the best available model on
 *  purpose. See INTELLIGENCE_CEILING for why.
 *
 *  Renders nothing when the model has not been scored. A zero-length bar
 *  would say "this model is bad" when what is true is "nobody has measured
 *  it". */
function Capability({
  percent,
  index,
}: {
  percent: number | null;
  /** The raw index, for the tooltip only — it cites the source without
   *  putting a second, differently-scaled number on the page. */
  index: number | null;
}) {
  if (percent === null) return null;
  return (
    <span
      className="adm-cap"
      title={
        index === null
          ? "Share of the top score we rate against"
          : `Artificial Analysis Intelligence Index: ${index}`
      }
    >
      <span className="adm-cap-label">intelligence {percent}%</span>
      <span className="adm-cap-bar" aria-hidden="true">
        {/* Floor of 2% so a very weak model still shows a sliver — a bar of
            literally zero width is indistinguishable from "not scored", which
            is a different fact. */}
        <span style={{ width: `${Math.max(2, percent)}%` }} />
      </span>
    </span>
  );
}

export function ModelPicker({
  tier,
  label,
  selected,
  options,
  onChange,
}: {
  tier: string;
  /** The answer mode's own name, for the control's accessible label. */
  label: string;
  selected: string;
  options: api.ModelCard[];
  onChange: (modelId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const baseId = useId();

  // A configured model the live list no longer carries. Kept at the top and
  // disabled rather than dropped: an admin whose mode names a retired model
  // has to be able to SEE that is what happened.
  const missing =
    selected && !options.some((o) => o.id === selected)
      ? ({
          id: selected,
          name: selected,
          available: false,
          blurb: null,
          usd_per_question: null,
          intelligence_index: null,
          intelligence_percent: null,
        } as api.ModelCard)
      : null;
  const rows = missing ? [missing, ...options] : options;
  const current = rows.find((r) => r.id === selected) ?? null;

  const close = useCallback((refocus = true) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  }, []);

  // Click anywhere else closes. Without this the menu survives a click on
  // another card and two menus can look open at once.
  useEffect(() => {
    if (!open) return;
    function onDocPointer(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocPointer);
    return () => document.removeEventListener("mousedown", onDocPointer);
  }, [open]);

  useEffect(() => {
    if (open) listRef.current?.focus();
  }, [open]);

  function openMenu() {
    const start = rows.findIndex((r) => r.id === selected);
    setActive(start >= 0 ? start : rows.findIndex((r) => r.available));
    setOpen(true);
  }

  /** Next selectable row in `step` direction, skipping disabled ones. */
  function move(step: number) {
    if (rows.length === 0) return;
    let next = active;
    for (let i = 0; i < rows.length; i += 1) {
      next = (next + step + rows.length) % rows.length;
      if (rows[next].available) break;
    }
    setActive(next);
  }

  function choose(index: number) {
    const row = rows[index];
    if (!row?.available) return;
    onChange(row.id);
    close();
  }

  function onTriggerKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openMenu();
    }
  }

  function onListKey(e: React.KeyboardEvent) {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        move(1);
        break;
      case "ArrowUp":
        e.preventDefault();
        move(-1);
        break;
      case "Home":
        e.preventDefault();
        setActive(rows.findIndex((r) => r.available));
        break;
      case "End":
        e.preventDefault();
        setActive(rows.length - 1 - [...rows].reverse().findIndex((r) => r.available));
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        choose(active);
        break;
      case "Escape":
        e.preventDefault();
        close();
        break;
      case "Tab":
        // Not prevented — Tab should move on, it just must not leave an
        // orphaned menu open behind it.
        close(false);
        break;
      default:
        break;
    }
  }

  const currentCost = perQuestion(current?.usd_per_question ?? null);

  return (
    <div className="adm-select" ref={rootRef} data-testid={`admin-picker-${tier}`}>
      <button
        type="button"
        ref={triggerRef}
        className={open ? "adm-select-trigger is-open" : "adm-select-trigger"}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Model for ${label}`}
        onClick={() => (open ? close(false) : openMenu())}
        onKeyDown={onTriggerKey}
      >
        <span className="adm-select-value">
          <span className="adm-select-name">
            {current ? current.name : "Pick a model"}
          </span>
          {current && !current.available ? (
            <span className="adm-chip is-gone">no longer available</span>
          ) : (
            <>
              {currentCost ? (
                <span className="adm-chip is-cost">{currentCost}</span>
              ) : null}
              <Capability
                percent={current?.intelligence_percent ?? null}
                index={current?.intelligence_index ?? null}
              />
            </>
          )}
        </span>
        <span className="adm-select-caret" aria-hidden="true" />
      </button>

      {open ? (
        <ul
          className="adm-select-menu"
          role="listbox"
          aria-label={`Model for ${label}`}
          tabIndex={-1}
          ref={listRef}
          aria-activedescendant={rows[active] ? `${baseId}-${active}` : undefined}
          onKeyDown={onListKey}
        >
          {rows.map((card, index) => {
            const cost = perQuestion(card.usd_per_question);
            const isSelected = card.id === selected;
            return (
              <li
                key={card.id}
                id={`${baseId}-${index}`}
                role="option"
                aria-selected={isSelected}
                aria-disabled={!card.available}
                className={[
                  "adm-select-option",
                  index === active ? "is-active" : "",
                  isSelected ? "is-on" : "",
                  card.available ? "" : "is-gone",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onMouseEnter={() => setActive(index)}
                onClick={() => choose(index)}
              >
                <span className="adm-option-head">
                  <span className="adm-option-name">{card.name}</span>
                  {!card.available ? (
                    <span className="adm-chip is-gone">no longer available</span>
                  ) : (
                    <>
                      {cost ? <span className="adm-chip is-cost">{cost}</span> : null}
                      <Capability
                        percent={card.intelligence_percent}
                        index={card.intelligence_index}
                      />
                    </>
                  )}
                </span>
                {card.blurb ? (
                  <span className="adm-option-blurb">{card.blurb}</span>
                ) : null}
              </li>
            );
          })}
          {/* In the menu rather than under the control: it is a caveat about
              the numbers you are reading right now, and on the page at rest
              it would be two lines of standing text nobody needs. */}
          <li className="adm-select-foot" role="presentation">
            Costs are worked out from a real question we timed, so treat them
            as a guide rather than a quote. Intelligence compares each model
            against the strongest one available, scored by Artificial
            Analysis — higher is better, and nothing reaches 100% so there is
            room for models that have not been built yet. Both come from
            OpenRouter each time this page opens.
          </li>
        </ul>
      ) : null}
    </div>
  );
}
