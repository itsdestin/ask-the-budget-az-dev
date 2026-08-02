// Empty-thread hero. Ported from web/components/WelcomeHero.tsx.

import Mascot from "./mascot/Mascot.js";

export default function WelcomeHero() {
  return (
    // The container scrolls internally so that on a very short viewport the
    // welcome content stays inside this area instead of bleeding into the
    // suggestion row / input bar below.
    // Mascot and headline only (Destin, 2026-08-02: "i want to eliminate all
    // text below 'hi lets look at the budget'"). The paragraph that used to
    // sit here listed the four publishers and promised a citation per claim —
    // both of which the honesty footer under the composer states permanently
    // ("Sources: JLBC · AGAO · AZ Legislature · Governor's Office · N
    // documents" / "Answers are cited, not guaranteed"), so nothing true was
    // only said here.
    <div className="chat-welcome">
      <Mascot pose="wave" size="hero" className="chat-welcome-mascot" />
      <h1>Hi — let&apos;s look at the budget.</h1>
    </div>
  );
}
