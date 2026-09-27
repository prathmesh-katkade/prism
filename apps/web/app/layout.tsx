import type { Metadata } from "next";
import "@prism/design-system/src/tokens.css";
import "./prism.css";
import "./atlas-investigation.css";

export const metadata: Metadata = {
  title: "PRISM — Analytical workspace",
  description: "The PRISM migration workspace shell."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
