import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { CitationBusProvider } from "@/state/citation-context";

export const metadata: Metadata = {
  title: "Ask the Budget AZ",
  description:
    "Multi-turn Q&A over Arizona state budget documents. Cited answers; refusal beats hallucination.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // data-theme drives the CSS-variable theme switch in globals.css.
  // Default light; a later appearance picker (Phase 2) can flip it.
  return (
    <html lang="en" data-theme="light">
      <body className="min-h-screen bg-canvas text-fg">
        <CitationBusProvider>{children}</CitationBusProvider>
      </body>
    </html>
  );
}
