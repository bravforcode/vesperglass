import React from 'react';
import { Calendar, Clock } from 'lucide-react';
import { CatalystEvent } from '../types';

interface CatalystTimelineProps {
  events: CatalystEvent[];
}

export const CatalystTimeline: React.FC<CatalystTimelineProps> = ({ events }) => {
  return (
    <div className="w-full rounded-xl p-3.5 border border-white/[0.08] bg-[#0C1017]/80">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
          <Calendar className="w-3.5 h-3.5 text-token-violet" />
          Upcoming Catalysts & Timeline
        </h4>
        <span className="text-[10px] font-mono text-slate-400">Scheduled Events</span>
      </div>

      <div className="relative pl-6 space-y-3.5 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
        {events.map((evt, idx) => {
          const isEarnings = evt.type.toUpperCase().includes('EARN');
          const isDividend = evt.type.toUpperCase().includes('DIV');
          const nodeColor = isEarnings
            ? 'bg-token-violet border-violet-400 shadow-glow-violet'
            : isDividend
            ? 'bg-token-emerald border-emerald-400 shadow-glow-emerald'
            : 'bg-token-amber border-amber-400 shadow-glow-amber';

          return (
            <div key={idx} className="relative group">
              {/* Glowing node marker */}
              <div
                className={`absolute -left-[22px] top-1 w-3 h-3 rounded-full border-2 ${nodeColor} transition-transform group-hover:scale-125`}
              />
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-white group-hover:text-token-cyan transition-colors">
                  {evt.title || evt.label}
                </span>
                <span className="text-[10px] font-mono text-token-cyan bg-cyan-950/40 px-2 py-0.5 rounded border border-cyan-800/40 flex items-center gap-1">
                  <Clock className="w-2.5 h-2.5" />
                  {evt.countdown}
                </span>
              </div>
              <p className="text-[11px] text-slate-400 mt-0.5 font-sans leading-relaxed">
                {evt.description || `Date: ${evt.date}`}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
};
