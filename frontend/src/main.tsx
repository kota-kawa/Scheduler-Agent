import React from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import App from "./app/App";
import "./styles/app.css";

// 日本語: SPA のマウント先を取得 / English: Grab SPA mount point
const rootEl = document.getElementById("app-root");
if (rootEl) {
  // 日本語: ルートを生成して App を描画 / English: Create root and render App
  const root = createRoot(rootEl);
  if (typeof flushSync === "function") {
    // 日本語: 初回描画を同期的に確定 / English: Flush initial render synchronously
    flushSync(() => {
      root.render(<App />);
    });
  } else {
    // 日本語: flushSync 非対応環境のフォールバック / English: Fallback render when flushSync is unavailable
    root.render(<App />);
  }
}
