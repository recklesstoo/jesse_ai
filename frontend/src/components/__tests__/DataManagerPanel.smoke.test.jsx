import React from "react";
import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";

import DataManagerPanel from "../DataManagerPanel.jsx";

describe("DataManagerPanel smoke", () => {
  it("renders day objects without throwing", () => {
    const html = renderToString(
      <DataManagerPanel
        disableFetch
        items={[
          {
            day: "2026-01-14",
            symbol: "MNQ",
            botId: "bot-1",
            bars: 100,
            trades: 2,
            first_ts_utc: "2026-01-14T00:00:00Z",
            last_ts_utc: "2026-01-14T23:59:59Z"
          }
        ]}
      />
    );
    expect(html).toContain("DATA MANAGER");
    expect(html).toContain("2026-01-14");
  });

  it("renders empty items", () => {
    const html = renderToString(<DataManagerPanel disableFetch items={[]} />);
    expect(html).toContain("DATA MANAGER");
  });

  it("renders missing fields safely", () => {
    const html = renderToString(<DataManagerPanel disableFetch items={[{}]} />);
    expect(html).toContain("DATA MANAGER");
  });
});

