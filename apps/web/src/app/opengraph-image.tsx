import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { ImageResponse } from "next/og";

// Preview card shown when the site link is shared (LinkedIn, WhatsApp, Slack...). Rendered at build time.
export const alt = "RestaurantIA Nexus: agentes de IA na operação de um restaurante, com aprovação humana";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const fontDir = join(process.cwd(), "node_modules/geist/dist/fonts/geist-sans");

export default async function OpenGraphImage() {
  const [regular, semibold] = await Promise.all([
    readFile(join(fontDir, "Geist-Regular.ttf")),
    readFile(join(fontDir, "Geist-SemiBold.ttf")),
  ]);
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 80px",
          background: "linear-gradient(135deg, #0b3b37 0%, #0f2a44 100%)",
          color: "#ffffff",
          fontFamily: "Geist",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <svg width="56" height="56" viewBox="0 0 32 32">
            <path d="M16 2.5 28 9.25v13.5L16 29.5 4 22.75V9.25z" fill="#2bb5a6" />
            <path
              d="M16 9.5v13M10.5 12.75 21.5 19.25M21.5 12.75 10.5 19.25"
              stroke="#ffffff"
              strokeWidth="1.6"
              strokeLinecap="round"
              fill="none"
            />
            <circle cx="16" cy="16" r="2.6" fill="#ffffff" />
          </svg>
          <div style={{ fontSize: 36, fontWeight: 600 }}>RestaurantIA Nexus</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          <div style={{ fontSize: 64, fontWeight: 600, lineHeight: 1.08, maxWidth: 980 }}>
            Agentes de IA na operação de um restaurante, com aprovação humana
          </div>
          <div style={{ fontSize: 28, lineHeight: 1.4, color: "#b9d8d4", maxWidth: 940 }}>
            Simulação de horário de pico, previsão de demanda e agentes que sugerem ações. O gerente aprova ou rejeita.
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 24, color: "#9fbcc4" }}>
          <div>Projeto de portfólio de João Victor Gualchi</div>
          <div>Demonstração ao vivo</div>
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        { name: "Geist", data: regular, weight: 400, style: "normal" },
        { name: "Geist", data: semibold, weight: 600, style: "normal" },
      ],
    },
  );
}
