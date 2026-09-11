import type { Metadata } from "next";
import "./prism.css";

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
