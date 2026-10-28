import React from 'react';

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
}

export const Sparkline: React.FC<SparklineProps> = ({ data, width = 64, height = 22 }) => {
  if (!data || data.length < 2) {
    return <div style={{ width, height }} className="bg-slate-800/40 rounded" />;
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1e-4;

  const points = data
    .map((val, idx) => {
      const x = (idx / (data.length - 1)) * width;
      const y = height - ((val - min) / range) * (height - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  const isUp = data[data.length - 1] >= data[0];
  const strokeColor = isUp ? '#10B981' : '#F43F5E';
  const fillColor = isUp ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)';

  const polygonPoints = `0,${height} ${points} ${width},${height}`;

  return (
    <svg width={width} height={height} className="overflow-visible inline-block">
      <polygon points={polygonPoints} fill={fillColor} />
      <polyline
        fill="none"
        stroke={strokeColor}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
};
