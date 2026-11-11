import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: "가상은행",
  description: "가상은행 모바일 웹 · 자연어 에이전트와 소비 관리",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className="h-full">
      <body className="min-h-full">
        <Providers>
          <div className="mx-auto min-h-dvh w-full max-w-[430px] bg-bg shadow-xl">{children}</div>
        </Providers>
      </body>
    </html>
  );
}
