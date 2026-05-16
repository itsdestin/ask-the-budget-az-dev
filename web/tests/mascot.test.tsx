import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import MascotBody from "../components/mascot/MascotBody";
import ArmsClasped from "../components/mascot/poses/ArmsClasped";
import ArmsWave from "../components/mascot/poses/ArmsWave";
import ArmsCrossed from "../components/mascot/poses/ArmsCrossed";
import ArmsClipboard from "../components/mascot/poses/ArmsClipboard";
import ArmsSides from "../components/mascot/poses/ArmsSides";
import ArmsHips from "../components/mascot/poses/ArmsHips";

describe("MascotBody", () => {
  it("renders the JLBC cap text and does not throw", () => {
    const html = renderToString(<svg viewBox="0 0 240 320"><MascotBody /></svg>);
    expect(html).toContain("JLBC");
    expect(html).toContain("var(--mascot-cap)");
    expect(html).toContain("var(--mascot-skin)");
  });
});

describe("pose components", () => {
  it("every pose renders without throwing", () => {
    for (const Arms of [ArmsClasped, ArmsWave, ArmsCrossed, ArmsClipboard, ArmsSides, ArmsHips]) {
      const html = renderToString(<svg viewBox="0 0 240 320"><Arms /></svg>);
      expect(html).toContain("var(--mascot-suit)");
    }
  });
});
