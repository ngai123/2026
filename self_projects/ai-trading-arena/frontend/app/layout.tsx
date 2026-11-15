import type { Metadata } from "next";
import { Poppins, Lora } from "next/font/google";
import "./globals.css";

// Anthropic brand typography: Poppins for headings, Lora for body.
const poppins = Poppins({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-poppins",
  display: "swap",
});

const lora = Lora({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-lora",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI Trading Arena",
  description: "Five AI models paper-trading US stocks, head to head.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${poppins.variable} ${lora.variable}`}>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
