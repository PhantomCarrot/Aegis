import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { ThemeProvider } from "@/hooks/useTheme";
import { TenantProvider } from "@/hooks/useTenant";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Aegis",
  description: "A private, multi-tenant conversational operations console.",
};

// Runs before hydration so the correct theme's class is already on <html>
// for the very first paint — ThemeProvider (a client component) only reads
// this back afterward, it never decides the initial theme itself.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem("aegis:theme");
    var dark = stored === "dark" || (stored !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    if (dark) document.documentElement.classList.add("dark");
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      // The inline theme script below adds/removes the "dark" class before
      // React hydrates (to avoid a flash of the wrong theme) — that's an
      // intentional, controlled mismatch, not a real one.
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">
        <ThemeProvider>
          <TenantProvider>{children}</TenantProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
