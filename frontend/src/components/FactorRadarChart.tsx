import React from 'react';
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Legend,
  Tooltip,
} from 'recharts';
import { RadarItem } from '../types';

interface FactorRadarChartProps {
  data: RadarItem[];
  ticker: string;
}

const CustomRadarTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    const item = payload[0].payload;
    return (
      <div className="bg-[#0C1017]/95 border border-white/10 rounded-lg p-2.5 shadow-xl text-xs font-mono">
        <p className="font-semibold text-white mb-1">{item.factor}</p>
        <p className="text-token-cyan">
          Target Stock: <span className="font-bold">{item.stockScore}</span>/100
        </p>
        <p className="text-slate-400">
          Sector Benchmark: <span className="font-bold">{item.sectorAvg}</span>/100
        </p>
      </div>
    );
  }
  return null;
};

export const FactorRadarChart: React.FC<FactorRadarChartProps> = ({ data, ticker }) => {
  return (
    <div className="w-full h-72 rounded-xl p-3 border border-white/[0.08] bg-[#0C1017]/80 flex flex-col">
      <div className="flex items-center justify-between mb-1">
        <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
          5-Axis Factor Radar vs Sector
        </h4>
        <span className="text-[10px] font-mono text-token-cyan px-2 py-0.5 rounded bg-cyan-950/40 border border-cyan-800/40">
          {ticker} vs Peer Median
        </span>
      </div>

      <div className="flex-1 w-full min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart cx="50%" cy="50%" outerRadius="70%" data={data}>
            <PolarGrid stroke="rgba(255, 255, 255, 0.08)" />
            <PolarAngleAxis
              dataKey="factor"
              tick={{ fill: '#94A3B8', fontSize: 11, fontFamily: 'Inter' }}
            />
            <PolarRadiusAxis
              angle={30}
              domain={[0, 100]}
              tick={{ fill: '#475569', fontSize: 9 }}
              stroke="rgba(255, 255, 255, 0.05)"
            />
            {/* Sector Average (Subtle Muted Area) */}
            <Radar
              name="Sector Median"
              dataKey="sectorAvg"
              stroke="#64748B"
              fill="#64748B"
              fillOpacity={0.15}
              strokeDasharray="3 3"
            />
            {/* Target Stock (Vibrant Glowing Neon Cyan) */}
            <Radar
              name={`${ticker} Score`}
              dataKey="stockScore"
              stroke="#00F2FE"
              fill="#00F2FE"
              fillOpacity={0.3}
              strokeWidth={2}
            />
            <Tooltip content={<CustomRadarTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: '11px', paddingTop: '4px' }}
              formatter={(value) => <span className="text-slate-300">{value}</span>}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
