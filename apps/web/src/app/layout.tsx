import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import { Providers } from "@/components/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "RestaurantIA Nexus", template: "%s · RestaurantIA Nexus" },
  description:
    "Plataforma de inteligência operacional para restaurantes com agentes de IA, previsão de demanda e aprovação humana. Projeto de portfólio com dados sintéticos.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f8fb" },
    { media: "(prefers-color-scheme: dark)", color: "#141824" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:shadow"
        >
          Pular para o conteúdo
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
