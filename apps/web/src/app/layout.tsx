import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import { Providers } from "@/components/providers";

import "./globals.css";

const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL ??
  (process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : "http://localhost:3000");

const description =
  "Projeto de portfólio: agentes de IA analisam a operação de um restaurante fictício em horário de pico e sugerem ações, que só são executadas com a aprovação de um gerente.";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: { default: "RestaurantIA Nexus", template: "%s · RestaurantIA Nexus" },
  description,
  openGraph: {
    type: "website",
    locale: "pt_BR",
    siteName: "RestaurantIA Nexus",
    title: "RestaurantIA Nexus",
    description,
    url: "/",
  },
  twitter: { card: "summary_large_image", title: "RestaurantIA Nexus", description },
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
