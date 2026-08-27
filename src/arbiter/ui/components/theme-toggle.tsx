"use client";

import { MoonIcon, SunIcon } from "@radix-ui/react-icons";
import { useTheme } from "next-themes";
import * as React from "react";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <button
      className="icon-button"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      title="Toggle theme"
    >
      <SunIcon className="icon-sun" style={{ display: theme === "dark" ? "none" : "block", width: "15px", height: "15px" }} />
      <MoonIcon className="icon-moon" style={{ display: theme === "dark" ? "block" : "none", width: "15px", height: "15px" }} />
      <span className="sr-only" style={{ display: "none" }}>Toggle theme</span>
    </button>
  );
}
