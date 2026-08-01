// A pill switch. Used for every on/off in the admin page.
//
// A real <input type="checkbox"> rather than a styled <button>: focusable,
// space-toggleable and announced as a switch for free.
//
// THE WRAPPER IS A <label>, and that is load-bearing rather than tidy markup.
// The first version stretched the invisible input across the whole control
// with `position:absolute; inset:0` and relied on it sitting on top. It did
// not: `.adm-toggle-track` is `position:relative`, so it painted ABOVE the
// input and ate every click aimed at the pill itself, while the statically
// positioned "On/Off" text next to it did not — so the switch could only be
// operated by clicking the word beside it (Destin, 2026-07-31). A <label>
// makes every descendant activate the control natively, whatever the paint
// order, so no stacking rule can reintroduce this.

export function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
  testId,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** The accessible name. Not rendered — the heading beside it is the
   *  visible label — so it has to say what is being switched. */
  label: string;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <label className={disabled ? "adm-toggle is-disabled" : "adm-toggle"}>
      <input
        type="checkbox"
        role="switch"
        aria-label={label}
        checked={checked}
        disabled={disabled}
        data-testid={testId}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="adm-toggle-track" aria-hidden="true">
        <span className="adm-toggle-knob" />
      </span>
      <span className="adm-toggle-state" aria-hidden="true">
        {checked ? "On" : "Off"}
      </span>
    </label>
  );
}
