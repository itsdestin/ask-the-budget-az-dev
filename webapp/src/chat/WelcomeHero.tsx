// Empty-thread hero. Ported from web/components/WelcomeHero.tsx.
//
// Mascot slightly LEFT of centre with the greeting in a bubble BESIDE him
// (Destin, 2026-08-02), rather than stacked underneath. He is addressing you
// now instead of captioning himself, which is the whole reason the character
// is on the page.
//
// The bubble is the app's own speech-bubble idiom: a card with ONE squared
// corner, aimed at the mascot. Deliberately NOT a triangle carat — Task 13
// deleted those from `.chat-bubble` because they hung 9px outside the box and
// read as clip-art next to the mockup's card grammar. Growing one back here,
// in the most-looked-at spot on the page, would undo that decision loudest.
//
// The paragraph that used to sit under the headline is gone (Destin,
// 2026-08-02: "i want to eliminate all text below 'hi lets look at the
// budget'"). It listed the four publishers and promised a citation per claim,
// both of which the honesty footer states permanently — so nothing true was
// only said here.

import Mascot from "./mascot/Mascot.js";

export default function WelcomeHero() {
  return (
    <div className="chat-welcome">
      <Mascot pose="wave" size="hero" className="chat-welcome-mascot" />
      {/* Still an h1: it is the only real heading in the thread — the route's
          own <h1> is clipped (see Ai.tsx) — so a screen reader needs this one
          to carry the page's opening. */}
      <h1 className="chat-welcome-bubble">Hi — let&apos;s look at the budget.</h1>
    </div>
  );
}
