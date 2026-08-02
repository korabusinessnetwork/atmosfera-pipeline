import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";

import "./globals.css";

const geist = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Atmosfera · painel",
  description: "Fila de aprovação do Atmosfera Viral.",
  // Painel interno atrás de login: indexar não traz nada e só convida tentativa
  // de acesso à tela de entrada.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#08080a",
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR" className={geist.variable}>
      <body className="min-h-dvh font-sans antialiased">{children}</body>
    </html>
  );
}
