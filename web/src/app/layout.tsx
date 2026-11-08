import type { Metadata } from 'next';
import './globals.css';
import Navbar from '@/components/Navbar';

export const metadata: Metadata = {
  title: 'AI Training Video Studio — Multilingual Presenter-Led Video Creator',
  description:
    'Professional AI Training Video Studio with local presenter avatars, dynamic motion visuals, AI storyboard planning, and cultural multilingual localization.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#090D1A] text-slate-100 antialiased selection:bg-cyan-500 selection:text-black">
        <Navbar />
        <main className="min-h-[calc(100vh-4rem)]">{children}</main>
      </body>
    </html>
  );
}
