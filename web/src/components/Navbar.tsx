'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Video,
  PlusCircle,
  FolderKanban,
  Film,
  Cpu,
} from 'lucide-react';
import { fetchProvidersStatus } from '@/lib/api';
import { ProviderStatus } from '@/types';

export default function Navbar() {
  const pathname = usePathname();
  const [providers, setProviders] = useState<ProviderStatus | null>(null);

  useEffect(() => {
    fetchProvidersStatus()
      .then(setProviders)
      .catch(() => null);
  }, []);

  const navLinks = [
    { label: 'Dashboard', href: '/', icon: Film },
    { label: 'Projects', href: '/projects', icon: FolderKanban },
    { label: 'Media Library', href: '/media', icon: Video },
    { label: 'Engine Status', href: '/settings', icon: Cpu },
  ];

  return (
    <header className="sticky top-0 z-50 w-full glass-panel border-b border-slate-800/80 bg-[#090D1A]/85 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand */}
        <Link href="/" className="flex items-center gap-3 group">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-sky-600 flex items-center justify-center shadow-lg shadow-cyan-500/20 group-hover:shadow-cyan-500/40 transition-all">
            <Video className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-lg tracking-tight text-white group-hover:text-cyan-400 transition-colors">
                AI Video Studio
              </span>
              <span className="text-[10px] uppercase tracking-wider font-extrabold bg-cyan-950 text-cyan-400 border border-cyan-800/80 px-1.5 py-0.5 rounded">
                v2 Pro
              </span>
            </div>
            <p className="text-[11px] text-slate-400 font-medium">Presenter-Led Multilingual Training</p>
          </div>
        </Link>

        {/* Primary Navigation */}
        <nav className="hidden md:flex items-center gap-1">
          {navLinks.map((link) => {
            const Icon = link.icon;
            const isActive =
              link.href === '/'
                ? pathname === '/'
                : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium transition-all ${
                  isActive
                    ? 'bg-slate-800 text-cyan-400 shadow-sm border border-slate-700/60'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                }`}
              >
                <Icon className={`w-4 h-4 ${isActive ? 'text-cyan-400' : 'text-slate-400'}`} />
                {link.label}
              </Link>
            );
          })}
        </nav>

        {/* Status & CTA */}
        <div className="flex items-center gap-3">
          {/* Hardware readiness badge */}
          {providers && (
            <div className="hidden lg:flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs">
              <span className="flex h-2 w-2 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              <span className="text-slate-300 font-medium">
                {providers.sadtalker.gpu_available ? 'SadTalker CUDA Ready' : 'SadTalker Ready'}
              </span>
            </div>
          )}

          <Link
            href="/create"
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-sky-500 hover:from-cyan-400 hover:to-sky-400 text-slate-950 font-semibold text-sm shadow-md shadow-cyan-500/20 hover:shadow-cyan-500/40 transition-all transform active:scale-95"
          >
            <PlusCircle className="w-4 h-4 text-slate-950" />
            <span>New Video</span>
          </Link>
        </div>
      </div>
    </header>
  );
}
