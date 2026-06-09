import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HomePro Realty — Voice AI Dashboard",
  description: "Real-time AI voice calling for real estate lead generation",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 min-h-screen antialiased">{children}</body>
    </html>
  );
}
