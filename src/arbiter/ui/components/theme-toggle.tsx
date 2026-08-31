"use client";

import { MoonIcon, SunIcon } from "@radix-ui/react-icons";
import { useTheme } from "next-themes";
import * as React from "react";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const dark = resolvedTheme === "dark";

  return (
    <button
      className="icon-button theme-toggle"
      onClick={() => setTheme(dark ? "light" : "dark")}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Switch to light theme" : "Switch to dark theme"}
    >
      <SunIcon className="icon-sun" aria-hidden="true" />
      <MoonIcon className="icon-moon" aria-hidden="true" />
      <span className="sr-only">{dark ? "Switch to light theme" : "Switch to dark theme"}</span>
    </button>
  );
}
