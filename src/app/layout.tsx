import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Trace: understand the code your AI agents write",
  description:
    "Practise reading, predicting, changing and verifying real code, including code an agent wrote, so you can review its output and debug the next problem yourself.",
};

export const viewport: Viewport = {
  themeColor: "#c98b7f",
};

// Marks that JS is running before first paint, so scroll reveals can start hidden.
// Without JS the class is never added and every section stays visible.
// "fonts" marks web fonts as ready (or 1.2s passed), so load-time headline reveals
// never re-render their blurred words when the font swaps in mid-animation.
const jsFlag = "var d=document.documentElement;d.classList.add('js');var f=function(){d.classList.add('fonts')};setTimeout(f,1200);document.fonts&&document.fonts.ready.then(f)";

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: jsFlag }} />
      </head>
      {/* Browser extensions (e.g. ColorZilla's cz-shortcut-listen) add attributes to <body>
          before React loads. This ignores attribute differences on <body> only, not its children. */}
      <body suppressHydrationWarning>
        <a
          href="#main"
          className="sr-only z-50 rounded-lg bg-surface px-4 py-2 text-sm font-medium text-foreground shadow-[var(--shadow-float)] focus:not-sr-only focus:fixed focus:top-4 focus:left-4"
        >
          Skip to content
        </a>
        <div className="frame-rim">
          <div className="site-canvas">{children}</div>
        </div>
      </body>
    </html>
  );
}
