import type { Metadata } from "next";

import { productConfig } from "@/lib/config";

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: `${productConfig.productName} — ${productConfig.parentBrand}`,
  description: "Evidence-first technical pre-screening for web-business acquisitions.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans text-foreground antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
