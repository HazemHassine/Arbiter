import type { Metadata, Viewport } from 'next';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { Analytics } from '@vercel/analytics/next';
import './global.css';
import { appName, siteUrl } from '@/lib/shared';

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#ffffff' },
    { media: '(prefers-color-scheme: dark)', color: '#09090b' },
  ],
  width: 'device-width',
  initialScale: 1,
};

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: 'Arbiter Documentation - Local Development Control Plane',
    template: '%s | Arbiter Documentation',
  },
  description:
    'A local-first Linux control plane for understanding, diagnosing, and safely operating Docker/Compose resources, host processes, ports, multi-project stacks, and AI coding agents.',
  keywords: [
    'Arbiter',
    'developer tools',
    'Docker',
    'Docker Compose',
    'Linux development',
    'port management',
    'port conflict reconciliation',
    'Model Context Protocol',
    'MCP',
    'Agent to Agent',
    'A2A',
    'local control plane',
    'process topology',
    'SRE operator',
    'LangGraph agent',
    'developer ergonomics',
    'terminal UI',
    'TUI',
  ],
  authors: [{ name: 'Hazem Hassine', url: 'https://github.com/HazemHassine' }],
  creator: 'Hazem Hassine',
  publisher: 'Hazem Hassine',
  applicationName: appName,
  generator: 'Next.js',
  referrer: 'origin-when-cross-origin',
  category: 'technology',
  alternates: {
    canonical: './',
  },
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: siteUrl,
    siteName: 'Arbiter Documentation',
    title: 'Arbiter Documentation - Local Development Control Plane',
    description:
      'A local-first Linux control plane for understanding, diagnosing, and safely operating Docker/Compose resources, host processes, ports, multi-project stacks, and AI coding agents.',
    images: [
      {
        url: '/og/docs/image.png',
        width: 1200,
        height: 630,
        alt: 'Arbiter - Local Development Control Plane',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Arbiter Documentation - Local Development Control Plane',
    description:
      'A local-first Linux control plane for understanding, diagnosing, and safely operating Docker/Compose resources, host processes, ports, multi-project stacks, and AI coding agents.',
    images: ['/og/docs/image.png'],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-video-preview': -1,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
};

export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="en" className="font-sans" suppressHydrationWarning>
      <body className="flex flex-col min-h-screen">
        <RootProvider>{children}</RootProvider>
        <Analytics />
      </body>
    </html>
  );
}
