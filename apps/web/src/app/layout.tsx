import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Linden_Hill } from "next/font/google";

import { productConfig } from "@/lib/config";

import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });
const lindenHill = Linden_Hill({ subsets: ["latin"], weight: "400", style: ["normal", "italic"], variable: "--font-serif" });

export const metadata: Metadata = {
  title: `${productConfig.productName} — ${productConfig.parentBrand}`,
  description: "Evidence-first technical pre-screening for web-business acquisitions.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable} ${lindenHill.variable}`}>
      <body className="min-h-screen font-sans text-foreground antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
