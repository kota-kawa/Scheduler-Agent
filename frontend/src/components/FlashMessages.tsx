import React from "react";

const { createElement: h } = React;

interface FlashMessagesProps {
  messages: string[];
}

export const FlashMessages = ({ messages }: FlashMessagesProps) => {
  if (!messages || messages.length === 0) return null;
  return h(
    "div",
    { className: "alert alert-info border-0 shadow-sm rounded-3 mb-4" },
    messages.map((msg, idx) =>
      h(
        "div",
        { key: `${idx}-${msg}` },
        h("i", { className: "bi bi-info-circle me-2" }),
        msg
      )
    )
  );
};
