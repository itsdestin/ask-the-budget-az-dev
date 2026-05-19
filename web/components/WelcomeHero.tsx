"use client";

import Mascot from "./mascot/Mascot";

export default function WelcomeHero() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-12 gap-2">
      <Mascot pose="wave" size="hero" className="mb-2" />
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
