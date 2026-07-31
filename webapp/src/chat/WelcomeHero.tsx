// Empty-thread hero. Ported from web/components/WelcomeHero.tsx.

import Mascot from "./mascot/Mascot.js";

export default function WelcomeHero() {
  return (
    // The container scrolls internally so that on a very short viewport the
    // welcome content stays inside this area instead of bleeding into the
    // suggestion row / input bar below.
    <div className="chat-welcome">
      <Mascot pose="wave" size="hero" className="chat-welcome-mascot" />
      <h1>Hi — let&apos;s look at the budget.</h1>
      <p>
        I&apos;ll search the JLBC Appropriations Reports, Baseline Books, AGAO
        Annual Financial Reports, and Governor&apos;s Executive Budget. Every
        claim gets a citation to the source page.
      </p>
    </div>
  );
}
