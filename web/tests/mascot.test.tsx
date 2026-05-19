import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import Mascot from "../components/mascot/Mascot";
import MascotBody from "../components/mascot/MascotBody";
import ArmsClasped from "../components/mascot/poses/ArmsClasped";
import ArmsWave from "../components/mascot/poses/ArmsWave";
import ArmsCrossed from "../components/mascot/poses/ArmsCrossed";
import ArmsClipboard from "../components/mascot/poses/ArmsClipboard";
import ArmsSides from "../components/mascot/poses/ArmsSides";
import ArmsHips from "../components/mascot/poses/ArmsHips";
import ArmsPushingGlasses from "../components/mascot/poses/ArmsPushingGlasses";
import GlassesUp from "../components/mascot/poses/GlassesUp";
import MascotTyping from "../components/mascot/MascotTyping";
import MascotPresenting from "../components/mascot/MascotPresenting";

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

describe("idle-moment art components", () => {
  it("ArmsPushingGlasses renders without throwing and contains skin color", () => {
    const html = renderToString(<svg viewBox="0 0 240 320"><ArmsPushingGlasses /></svg>);
    expect(html).toContain("var(--mascot-skin)");
  });

  it("GlassesUp renders without throwing and contains skin color", () => {
    const html = renderToString(<svg viewBox="0 0 240 320"><GlassesUp /></svg>);
    expect(html).toContain("var(--mascot-skin)");
  });
});

describe("Mascot", () => {
  it("renders with role=img and an aria-label", () => {
    const html = renderToString(<Mascot pose="wave" size="hero" />);
    expect(html).toContain('role="img"');
    expect(html).toContain('aria-label="JLBC budget assistant"');
  });

  it("renders the chip size at 40x70", () => {
    const html = renderToString(<Mascot pose="clasped" size="chip" />);
    expect(html).toContain('width="40"');
    expect(html).toContain('height="70"');
  });

  it("includes the bob animation class when animate is not false", () => {
    const html = renderToString(<Mascot pose="clasped" size="hero" />);
    expect(html).toContain("mascot-animate");
  });

  it("omits the animation class when animate=false", () => {
    const html = renderToString(<Mascot pose="clasped" size="hero" animate={false} />);
    expect(html).not.toContain("mascot-animate");
  });

  it("renders every pose without throwing", () => {
    for (const pose of ["sides", "clasped", "wave", "crossed", "clipboard", "hips"] as const) {
      expect(() => renderToString(<Mascot pose={pose} size="hero" />)).not.toThrow();
    }
  });
});

describe("MascotTyping", () => {
  it("renders the seated working-loop scene", () => {
    const html = renderToString(<MascotTyping />);
    expect(html).toContain('aria-label="JLBC budget assistant — searching"');
    expect(html).toContain("mascot-typing-cursor");
    expect(html).toContain("var(--mascot-skin)");
    expect(html).toContain("var(--mascot-cap)");
  });
});

describe("MascotPresenting", () => {
  it("renders the presenting scene", () => {
    const html = renderToString(<MascotPresenting />);
    expect(html).toContain('aria-label="JLBC budget assistant — presenting results"');
    expect(html).toContain("var(--mascot-skin)");
    expect(html).toContain("var(--mascot-cap)");
    expect(html).toContain("mascot-typing-cursor");
  });
});
