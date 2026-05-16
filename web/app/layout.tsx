import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Source_Serif_4, Inter } from "next/font/google";

import { CitationBusProvider } from "@/state/citation-context";

// Self-hosted and inlined by next/font — no render-blocking CDN request.
// display:swap shows fallback text instantly, then swaps in the web font.
// The CSS-variable names match the @theme mapping in globals.css.
const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-source-serif",
  display: "swap",
});
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Ask the Budget AZ",
  description:
    "Multi-turn Q&A over Arizona state budget documents. Cited answers; refusal beats hallucination.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sourceSerif.variable} ${inter.variable}`}>
      <body className="min-h-screen bg-canvas text-fg">
        <CitationBusProvider>{children}</CitationBusProvider>
      </body>
    </html>
  );
}
