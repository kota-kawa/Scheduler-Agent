import React from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import App from "./app/App";
import "./styles/app.css";

const rootEl = document.getElementById("app-root");
if (rootEl) {
  const root = createRoot(rootEl);
  if (typeof flushSync === "function") {
    flushSync(() => {
      root.render(<App />);
    });
  } else {
    root.render(<App />);
  }
}
