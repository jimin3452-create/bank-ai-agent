import type { NextConfig } from "next";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // 모든 화면이 로그인 후 사용자별 데이터를 보여 주는 클라이언트 앱이라 Cache Components는 쓰지 않는다.
  cacheComponents: false,
  partialPrefetching: false,
  // 브라우저는 같은 출처의 /api 로만 호출한다(쿠키 인증, CORS 불필요).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
