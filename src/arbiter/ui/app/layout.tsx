import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Arbiter — Local Development Control Plane",
  description: "Understand and safely reconcile the local development environment.",
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#080b11",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        {children}
        <script src="/ui/icons.js" defer />
      </body>
    </html>
  );
}
