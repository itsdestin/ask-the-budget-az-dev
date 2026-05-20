import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import SystemHealthBanner from "../components/SystemHealthBanner";

describe("SystemHealthBanner", () => {
  it("renders the offline message inside an alert role", () => {
    const html = renderToString(<SystemHealthBanner />);
    expect(html).toContain("role=\"alert\"");
    expect(html).toContain("offline");
  });

  it("surfaces the underlying reason in parentheses when supplied", () => {
    const html = renderToString(<SystemHealthBanner reason="HTTP 503" />);
    expect(html).toContain("HTTP 503");
  });
});
