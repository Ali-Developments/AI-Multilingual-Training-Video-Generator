'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  FolderKanban,
  PlusCircle,
  Trash2,
  Copy,
  ArrowRight,
  RefreshCw,
  Search,
} from 'lucide-react';
import { fetchProjectSummaries, deleteProject, duplicateProject } from '@/lib/api';
import { ProjectSummary } from '@/types';

export default function ProjectsCatalogPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      setLoading(true);
      const data = await fetchProjectSummaries();
      setProjects(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = projects.filter((p) =>
    p.title.toLowerCase().includes(search.toLowerCase()) ||
    p.project_id.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <FolderKanban className="w-6 h-6 text-cyan-400" />
            Projects Catalog
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Browse, manage, and inspect all created training video modules
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search projects..."
              className="pl-9 pr-4 py-1.5 rounded-xl bg-slate-900 border border-slate-800 text-xs text-white focus:outline-none focus:border-cyan-500"
            />
          </div>

          <Link
            href="/create"
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-slate-950 font-bold text-xs shadow-md transition-all"
          >
            <PlusCircle className="w-4 h-4" />
            <span>New Video</span>
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="py-20 flex justify-center">
          <RefreshCw className="w-6 h-6 text-cyan-400 animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 rounded-xl border border-dashed border-slate-800 p-8 text-slate-400 text-sm">
          No matching projects found.
        </div>
      ) : (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden shadow-lg">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/80 border-b border-slate-800 text-slate-400 uppercase tracking-wider font-semibold">
              <tr>
                <th className="p-4">Project Title</th>
                <th className="p-4">Duration</th>
                <th className="p-4">Languages</th>
                <th className="p-4">Avatar</th>
                <th className="p-4">Status</th>
                <th className="p-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {filtered.map((p) => (
                <tr
                  key={p.project_id}
                  onClick={() => router.push(`/studio/${p.project_id}`)}
                  className="hover:bg-slate-800/40 cursor-pointer transition-colors"
                >
                  <td className="p-4 font-semibold text-white">
                    <div className="line-clamp-1">{p.title}</div>
                    <div className="text-[11px] font-mono text-slate-500 font-normal">{p.project_id}</div>
                  </td>
                  <td className="p-4 font-mono text-slate-300">
                    {p.duration_seconds.toFixed(1)}s
                  </td>
                  <td className="p-4">
                    <div className="flex gap-1 flex-wrap">
                      <span className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] text-slate-300">
                        {p.source_language}
                      </span>
                      {p.target_languages.map((l) => (
                        <span key={l} className="px-1.5 py-0.5 rounded bg-cyan-950 border border-cyan-800 text-[10px] text-cyan-400">
                          {l}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="p-4 capitalize text-slate-400">
                    {p.avatar_provider}
                  </td>
                  <td className="p-4">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                        p.status === 'completed'
                          ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                          : p.status === 'running'
                          ? 'bg-cyan-950 text-cyan-400 border border-cyan-800'
                          : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      {p.status}
                    </span>
                  </td>
                  <td className="p-4 text-right">
                    <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                      <button
                        title="Duplicate"
                        onClick={async () => {
                          await duplicateProject(p.project_id);
                          await load();
                        }}
                        className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white"
                      >
                        <Copy className="w-3.5 h-3.5" />
                      </button>
                      <button
                        title="Delete"
                        onClick={async () => {
                          if (confirm('Delete project?')) {
                            await deleteProject(p.project_id);
                            await load();
                          }
                        }}
                        className="p-1 rounded hover:bg-rose-950 text-slate-400 hover:text-rose-400"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => router.push(`/studio/${p.project_id}`)}
                        className="p-1 rounded hover:bg-cyan-950 text-cyan-400 ml-1"
                      >
                        <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
