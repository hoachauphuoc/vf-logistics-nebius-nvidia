import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { AppShell } from "@/components/layout/AppShell";

import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
  display: "swap",
});

// Used for the inference-metadata block, where a proportional font would make
// token counts and hashes ragged and hard to compare down a column.
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Trade Compliance Auditor",
  description:
    "Autonomous screening for import and export declarations: sanctions, " +
    "dual-use classification and adverse media, with the provenance to defend " +
    "every verdict.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      // `dark` is set here rather than toggled at runtime: this console is
      // dark-only, and leaving it to a client effect would flash a light
      // background before hydration.
      className={`dark ${inter.variable} ${jetbrainsMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full">
        <Providers>
          {/* The shell lives here rather than in each page so that navigating
              between sections does not unmount the sidebar -- which would reset
              its scroll position and re-run the review-count query on every
              click. */}
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
