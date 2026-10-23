import type { Metadata, Viewport } from "next";
import { Header } from "@/components/header";
import { DISCLAIMER } from "@/lib/config";
import "./globals.css";

export const metadata: Metadata = {
  title: "Saath Gaadi: group car buying",
  description: "Join verified buyers for the same car in your city and make dealers compete on the on-road price.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#f97316" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN">
      <body className="min-h-dvh">
        <Header />
        <main className="container pb-16 pt-4">{children}</main>
        <footer className="border-t py-6 text-xs text-muted-foreground">
          <div className="container space-y-1">
            <p>{DISCLAIMER}</p>
            <p>Saath Gaadi connects buyers with authorised dealers. Sales, invoicing and delivery are between you and the dealer.</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
