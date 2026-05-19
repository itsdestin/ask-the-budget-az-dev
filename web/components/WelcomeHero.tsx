"use client";

import Mascot from "./mascot/Mascot";

export default function WelcomeHero() {
  return (
    // overflow-y-auto ensures that if the viewport is very short the
    // welcome content scrolls inside this area instead of bleeding into
    // the SuggestionRow / input bar below.
    <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-8 gap-2 overflow-y-auto">
      {/* max-h-[55vh] caps the hero mascot's rendered height on short
          viewports; w-auto lets the width scale proportionally from the
          viewBox, preserving the pixel-art aspect ratio. */}
      <Mascot pose="wave" size="hero" className="mb-2 max-h-[55vh] w-auto" />
      <h1 className="font-serif text-3xl font-bold text-fg">
        Hi — let&apos;s look at the budget.
      </h1>
      <p className="text-fg-2 max-w-xl">
        I&apos;ll search the JLBC Appropriations Reports, Baseline Books, AGAO Annual
        Financial Reports, and Governor&apos;s Executive Budget. Every claim gets a
        citation to the source page.
      </p>
    </div>
  );
}
