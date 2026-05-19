interface Props {
  /** YouCoded connection status — drives the status dot color. */
  connected: boolean;
}

export default function Footer({ connected }: Props) {
  return (
    <footer className="flex-shrink-0 border-t border-edge bg-panel/40 px-4 h-[26px]
                       flex items-center justify-between text-[11px] font-mono text-fg-muted">
      <span>Sources: JLBC · AGAO · AZ Legislature · Governor&apos;s Office</span>
      <span>Answers are cited, not guaranteed. Verify against sources.</span>
      <span className="flex items-center gap-2">
        <span
          className="inline-block w-2 h-2 rounded-full"
          style={{ background: connected ? "var(--success)" : "var(--danger)" }}
          aria-label={connected ? "YouCoded connected" : "YouCoded disconnected"}
        />
        382 docs · FY2024–26
      </span>
    </footer>
  );
}
