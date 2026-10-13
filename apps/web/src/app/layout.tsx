import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {title: { default: "Capital Intelligence", template: "%s · Capital Intelligence" }, description: "Inteligência financeira com dados verificáveis, contexto e transparência.", robots: {index:false,follow:false} };
export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) { return <html lang="pt-BR"><body>{children}</body></html>; }

