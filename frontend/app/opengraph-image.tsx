import { ImageResponse } from "next/og";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const LOGO_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect width="32" height="32" rx="8" fill="#EE672F" />
  <path d="M8 23V10l8 8 8-8v13" fill="none" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />
</svg>`;
const LOGO_DATA_URI = `data:image/svg+xml,${encodeURIComponent(LOGO_SVG)}`;

// Next.js's App Router convention: a default export here auto-generates the
// og:image/twitter:image meta tags for the whole site (root layout has no
// openGraph.images of its own to override this) -- without it, sharing the
// link anywhere (Slack, WhatsApp, LinkedIn) showed only a bare title/
// description with no visual, confirmed directly against a real WhatsApp
// share preview before this existed.
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "80px",
          backgroundColor: "#0a0a0a",
          backgroundImage: "radial-gradient(circle at 75% 30%, #2a1208 0%, #0a0a0a 55%)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <img src={LOGO_DATA_URI} width={64} height={64} alt="" />
          <div style={{ display: "flex", fontSize: 56, fontWeight: 700, color: "#fafafa" }}>MageWiki-AI</div>
        </div>
        <div style={{ display: "flex", marginTop: 32, fontSize: 32, color: "#a1a1aa", maxWidth: 920 }}>
          AI-powered catalog and chat agent for Magento 2 modules
        </div>
        <div style={{ display: "flex", marginTop: 56, fontSize: 24, color: "#71717a" }}>
          Scan · Quality &amp; security checks · Dependency graph · Chat with citations
        </div>
      </div>
    ),
    { ...size }
  );
}
