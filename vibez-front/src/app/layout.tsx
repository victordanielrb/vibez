import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vibez — Find Music by Mood",
  description: "Upload an image and discover tracks that match your vibe",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-vibez-dark text-white antialiased">
        {children}
      </body>
    </html>
  );
}
