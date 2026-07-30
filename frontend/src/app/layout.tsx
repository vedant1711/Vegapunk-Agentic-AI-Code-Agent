import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vegapunk - Autonomous Coding Agent",
  description:
    "Trace view for Vegapunk, an autonomous agent that resolves GitHub issues by planning, writing code, running tests, and opening a pull request.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased">{children}</body>
    </html>
  );
}
