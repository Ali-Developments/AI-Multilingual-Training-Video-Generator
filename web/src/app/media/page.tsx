'use client';

import React, { useState } from 'react';
import { Video, Image as ImageIcon, Upload } from 'lucide-react';

export default function MediaLibraryPage() {
  const [selectedTab, setSelectedTab] = useState<'all' | 'video' | 'image'>('all');
  const [mediaItems, setMediaItems] = useState([
    {
      id: '1',
      name: 'kitchen_prep_action.mp4',
      type: 'video',
      size: '14.2 MB',
      duration: '12.4s',
      url: '/assets/sample_video.mp4',
      tags: ['Culinary', 'Kabsa', 'Prep'],
    },
    {
      id: '2',
      name: 'avatar_portrait.png',
      type: 'image',
      size: '1.8 MB',
      duration: 'Still',
      url: '/assets/avatar_portrait.png',
      tags: ['Presenter', 'Studio', 'Portrait'],
    },
    {
      id: '3',
      name: 'phishing_sample_email.png',
      type: 'image',
      size: '850 KB',
      duration: 'Still',
      url: '/assets/phishing.png',
      tags: ['Security', 'Infographic'],
    },
  ]);

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.[0]) return;
    const file = e.target.files[0];
    const isVid = file.type.includes('video') || file.name.endsWith('.mp4');
    const newItem = {
      id: Date.now().toString(),
      name: file.name,
      type: isVid ? 'video' : 'image',
      size: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
      duration: isVid ? '10.0s' : 'Still',
      url: URL.createObjectURL(file),
      tags: ['User Upload'],
    };
    setMediaItems([newItem, ...mediaItems]);
    alert(`File '${file.name}' added to Media Library.`);
  };

  const filtered = mediaItems.filter(
    (m) => selectedTab === 'all' || m.type === selectedTab
  );

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Video className="w-6 h-6 text-cyan-400" />
            Media & B-Roll Library
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Store video clips, images, and graphics for scene presentation & motion visuals
          </p>
        </div>

        <label className="flex items-center gap-2 px-4 py-2 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-slate-950 font-bold text-xs shadow-md cursor-pointer transition-all">
          <Upload className="w-4 h-4" />
          <span>Upload Media</span>
          <input
            type="file"
            accept=".mp4,.mov,.webm,.png,.jpg,.jpeg,.webp"
            onChange={handleUpload}
            className="hidden"
          />
        </label>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
        {(['all', 'video', 'image'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setSelectedTab(tab)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold capitalize transition-all ${
              selectedTab === tab
                ? 'bg-slate-800 text-cyan-400 border border-slate-700'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            {tab}s
          </button>
        ))}
      </div>

      {/* Media Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {filtered.map((item) => (
          <div
            key={item.id}
            className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden shadow-md hover:border-cyan-500/40 transition-all flex flex-col justify-between"
          >
            <div className="aspect-video w-full bg-slate-950 flex items-center justify-center relative border-b border-slate-800">
              {item.type === 'video' ? (
                <Video className="w-10 h-10 text-cyan-500/50" />
              ) : (
                <ImageIcon className="w-10 h-10 text-emerald-500/50" />
              )}
              <span className="absolute bottom-2 right-2 px-1.5 py-0.5 rounded bg-black/80 text-[10px] font-mono text-slate-300">
                {item.duration}
              </span>
              <span className="absolute top-2 left-2 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-slate-800/80 text-cyan-300">
                {item.type}
              </span>
            </div>

            <div className="p-3 space-y-2">
              <div className="text-xs font-semibold text-white truncate" title={item.name}>
                {item.name}
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-400">
                <span>{item.size}</span>
                <span className="text-[10px] font-mono text-slate-500">Local Cache</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
