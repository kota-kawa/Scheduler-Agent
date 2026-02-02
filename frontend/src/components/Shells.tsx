import React, { Fragment } from "react";
import { withPrefix } from "../api/client";
import { ChatSidebar } from "./ChatSidebar";
import { FlashMessages } from "./FlashMessages";

const { createElement: h } = React;

interface NavBarProps {}

export const NavBar = (_props: NavBarProps) =>
  h(
    "nav",
    { className: "navbar navbar-expand-lg fixed-top" },
    h(
      "div",
      { className: "container" },
      h(
        "a",
        { className: "navbar-brand", href: withPrefix("/") },
        h("i", { className: "bi bi-calendar-check me-2" }),
        "ルーチン・スケジューラー"
      ),
      h(
        "button",
        {
          className: "navbar-toggler",
          type: "button",
          "data-bs-toggle": "collapse",
          "data-bs-target": "#navbarNav",
        },
        h("span", { className: "navbar-toggler-icon" })
      ),
      h(
        "div",
        { className: "collapse navbar-collapse", id: "navbarNav" },
        h(
          "ul",
          { className: "navbar-nav ms-auto" },
          h(
            "li",
            { className: "nav-item" },
            h("a", { className: "nav-link", href: withPrefix("/") }, "カレンダー")
          ),
          h(
            "li",
            { className: "nav-item" },
            h("a", { className: "nav-link", href: withPrefix("/evaluation") }, "評価")
          ),
          h(
            "li",
            { className: "nav-item" },
            h("a", { className: "nav-link", href: withPrefix("/routines") }, "ルーチン設定")
          )
        )
      )
    )
  );

interface MainShellProps {
  children: React.ReactNode;
  onRefresh: (ids?: Array<string | number>) => void;
  flashMessages: string[];
  onModelChange: (model: string) => void;
}

export const MainShell = ({ children, onRefresh, flashMessages, onModelChange }: MainShellProps) =>
  h(
    Fragment,
    null,
    h(NavBar),
    h(
      "div",
      { className: "app-shell" },
      h(ChatSidebar, { onRefresh, onModelChange }),
      h(
        "main",
        { className: "main" },
        h(
          "div",
          { className: "container main__container" },
          h(FlashMessages, { messages: flashMessages }),
          children
        )
      )
    )
  );

interface StandaloneShellProps {
  children: React.ReactNode;
}

export const StandaloneShell = ({ children }: StandaloneShellProps) =>
  h("div", { className: "standalone-container" }, children);

interface EmbedShellProps {
  yearTitle: string;
  nav: React.ReactNode;
  content: React.ReactNode;
}

export const EmbedShell = ({ yearTitle, nav, content }: EmbedShellProps) =>
  h(
    "div",
    { className: "embed-shell" },
    h(
      "div",
      { className: "d-flex justify-content-between align-items-center embed-header" },
      h(
        "div",
        null,
        h("h2", { className: "mb-0" }, yearTitle || ""),
        h("p", { className: "text-muted mb-0" }, "Scheduler Agent")
      ),
      nav
    ),
    h("div", { className: "calendar-wrapper" }, content)
  );
