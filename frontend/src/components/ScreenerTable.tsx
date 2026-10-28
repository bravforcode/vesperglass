import React, { useMemo, useRef, useState } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  SortingState,
  createColumnHelper,
  flexRender,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ArrowUpDown, ArrowUp, ArrowDown, ExternalLink } from 'lucide-react';
import { StrategyBadge } from './StrategyBadges';
import { RiskRewardPill } from './RiskRewardPill';
import { Sparkline } from './Sparkline';
import { Candidate } from '../types';

interface ScreenerTableProps {
  candidates: Candidate[];
  onSelectCandidate: (ticker: string) => void;
  isLoading: boolean;
}

const columnHelper = createColumnHelper<Candidate>();

export const ScreenerTable: React.FC<ScreenerTableProps> = ({
  candidates,
  onSelectCandidate,
  isLoading,
}) => {
  const [sorting, setSorting] = useState<SortingState>([
    { id: 'confidence_score', desc: true },
  ]);

  const columns = useMemo(
    () => [
      // 1. Ticker & Company
      columnHelper.accessor('ticker', {
        header: 'Ticker / Company',
        cell: (info) => {
          const row = info.row.original;
          return (
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-sm text-white group-hover:text-token-cyan transition-colors">
                  {row.ticker}
                </span>
                <span className="text-[10px] font-sans px-1.5 py-0.5 rounded bg-surface-elevated text-slate-400 border border-white/[0.04]">
                  {row.sector}
                </span>
              </div>
              <span className="text-xs text-slate-400 truncate max-w-[160px]">
                {row.name}
              </span>
            </div>
          );
        },
      }),

      // 2. Price / 24h Change & Sparkline
      columnHelper.accessor('price', {
        header: 'Price / 24h Δ',
        cell: (info) => {
          const row = info.row.original;
          const isUp = row.change_24h_pct >= 0;
          return (
            <div className="flex items-center justify-between gap-3 font-mono tabular-nums">
              <div className="text-right">
                <div className="text-sm font-semibold text-white">
                  ${row.price.toFixed(2)}
                </div>
                <div className={`text-xs font-medium ${isUp ? 'text-token-emerald' : 'text-token-rose'}`}>
                  {isUp ? '+' : ''}{row.change_24h_pct.toFixed(2)}%
                </div>
              </div>
              <Sparkline data={row.sparkline} width={56} height={20} />
            </div>
          );
        },
      }),

      // 3. Strategy Match
      columnHelper.accessor((row) => row.strategies[0], {
        id: 'strategy',
        header: 'Strategy Match',
        cell: (info) => {
          const strat = info.getValue() || 'MOMENTUM_BREAKOUT';
          return <StrategyBadge strategy={strat} size="sm" />;
        },
      }),

      // 4. Factor Score
      columnHelper.accessor('confidence_score', {
        header: 'Factor Score',
        cell: (info) => {
          const score = info.getValue();
          const isHigh = score >= 80;
          return (
            <div className="flex items-center justify-center">
              <span
                className={`font-mono tabular-nums text-xs font-bold px-2.5 py-1 rounded-md ${
                  isHigh
                    ? 'bg-cyan-950/60 text-token-cyan border border-cyan-500/40 shadow-glow-cyan'
                    : 'bg-surface-elevated text-slate-300 border border-white/[0.06]'
                }`}
              >
                {score}/100
              </span>
            </div>
          );
        },
      }),

      // 5. Target Return
      columnHelper.accessor((row) => row.setup.target_return_pct, {
        id: 'target_return_pct',
        header: 'Target Upside',
        cell: (info) => {
          const val = info.getValue();
          return (
            <div className="text-right font-mono tabular-nums text-sm font-bold text-token-emerald">
              +{val.toFixed(1)}%
            </div>
          );
        },
      }),

      // 6. Trade Setup
      columnHelper.accessor((row) => row.setup.entry_price, {
        id: 'setup',
        header: 'Trade Setup',
        cell: (info) => {
          const setup = info.row.original.setup;
          return (
            <div className="flex flex-col text-xs font-mono tabular-nums">
              <div className="text-slate-200">
                <span className="text-token-cyan font-semibold">${setup.entry_price.toFixed(2)}</span>
                <span className="text-slate-500 mx-1">➔</span>
                <span className="text-token-emerald font-semibold">${setup.target_price.toFixed(2)}</span>
              </div>
              <span className="text-[10px] text-slate-400">
                Stop: <span className="text-token-rose">${setup.stop_loss.toFixed(2)}</span>
              </span>
            </div>
          );
        },
      }),

      // 7. Risk : Reward
      columnHelper.accessor((row) => row.setup.risk_reward_ratio, {
        id: 'risk_reward_ratio',
        header: 'Risk : Reward',
        cell: (info) => <RiskRewardPill ratio={info.getValue()} />,
      }),

      // 8. Catalyst
      columnHelper.accessor((row) => row.catalysts[0]?.countdown, {
        id: 'catalyst',
        header: 'Catalyst',
        cell: (info) => {
          const countdown = info.getValue();
          return (
            <span className="text-[11px] font-mono text-slate-300 bg-surface px-2 py-0.5 rounded border border-white/[0.04]">
              {countdown ? `Earnings in ${countdown}` : 'Upcoming EOD'}
            </span>
          );
        },
      }),

      // 9. Action Button
      columnHelper.display({
        id: 'action',
        header: '',
        cell: (info) => (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onSelectCandidate(info.row.original.ticker);
            }}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-surface hover:bg-token-cyan/20 border border-white/[0.06] hover:border-token-cyan/40 text-xs font-medium text-slate-300 hover:text-token-cyan transition-all"
          >
            <span>Analyze</span>
            <ExternalLink className="w-3 h-3" />
          </button>
        ),
      }),
    ],
    [onSelectCandidate]
  );

  const table = useReactTable({
    data: candidates,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const tableContainerRef = useRef<HTMLDivElement>(null);
  const rows = table.getRowModel().rows;

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => tableContainerRef.current,
    estimateSize: () => 58,
    overscan: 10,
  });

  return (
    <div className="w-full glass-panel rounded-2xl overflow-hidden shadow-glass-card border border-white/[0.08]">
      {/* Mobile Card Feed View (Hidden on md and up) */}
      <div className="block md:hidden divide-y divide-white/[0.06]">
        {isLoading ? (
          <div className="p-8 text-center text-slate-400 font-mono text-xs">
            Scanning 1,015 US equities...
          </div>
        ) : candidates.length === 0 ? (
          <div className="p-8 text-center text-slate-400 font-mono text-xs">
            No candidates match active filter criteria.
          </div>
        ) : (
          candidates.map((cand) => (
            <div
              key={cand.ticker}
              onClick={() => onSelectCandidate(cand.ticker)}
              className="p-4 space-y-2.5 hover:bg-surface-elevated/50 active:bg-surface-elevated transition-colors cursor-pointer"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-base text-white">
                    {cand.ticker}
                  </span>
                  <span className="text-xs text-slate-400 truncate max-w-[120px]">
                    {cand.name}
                  </span>
                </div>
                <div className="text-right font-mono tabular-nums">
                  <div className="text-sm font-bold text-white">${cand.price.toFixed(2)}</div>
                  <div className={`text-xs ${cand.change_24h_pct >= 0 ? 'text-token-emerald' : 'text-token-rose'}`}>
                    {cand.change_24h_pct >= 0 ? '+' : ''}{cand.change_24h_pct.toFixed(2)}%
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between gap-2">
                <StrategyBadge strategy={cand.strategies[0]} size="sm" />
                <span className="font-mono font-bold text-xs text-token-emerald">
                  +{cand.setup.target_return_pct.toFixed(1)}% Upside
                </span>
                <RiskRewardPill ratio={cand.setup.risk_reward_ratio} />
              </div>

              <div className="flex items-center justify-between text-xs text-slate-400 font-mono pt-1">
                <span>E: ${cand.setup.entry_price.toFixed(2)} ➔ T: ${cand.setup.target_price.toFixed(2)}</span>
                <span className="text-token-cyan text-[11px]">Analyze ➔</span>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Desktop Virtualized Table (Visible on md and up) */}
      <div className="hidden md:block">
        {/* Table Header */}
        <div className="border-b border-white/[0.08] bg-[#0C1017]">
          {table.getHeaderGroups().map((headerGroup) => (
            <div key={headerGroup.id} className="flex items-center px-4 py-3 text-xs font-semibold text-slate-400">
              {headerGroup.headers.map((header) => {
                const canSort = header.column.getCanSort();
                const isSorted = header.column.getIsSorted();
                return (
                  <div
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className={`flex items-center gap-1 select-none ${
                      header.id === 'ticker'
                        ? 'w-1/5'
                        : header.id === 'price'
                        ? 'w-[14%] justify-end text-right'
                        : header.id === 'strategy'
                        ? 'w-[14%]'
                        : header.id === 'confidence_score'
                        ? 'w-[10%] justify-center text-center'
                        : header.id === 'target_return_pct'
                        ? 'w-[10%] justify-end text-right'
                        : header.id === 'setup'
                        ? 'w-[14%]'
                        : header.id === 'risk_reward_ratio'
                        ? 'w-[9%]'
                        : header.id === 'catalyst'
                        ? 'w-[11%]'
                        : 'w-[7%] justify-end'
                    } ${canSort ? 'cursor-pointer hover:text-slate-200' : ''}`}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {canSort && (
                      <span className="text-slate-500">
                        {isSorted === 'asc' ? (
                          <ArrowUp className="w-3 h-3 text-token-cyan" />
                        ) : isSorted === 'desc' ? (
                          <ArrowDown className="w-3 h-3 text-token-cyan" />
                        ) : (
                          <ArrowUpDown className="w-3 h-3 opacity-40 hover:opacity-100" />
                        )}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Virtualized Table Rows */}
        <div
          ref={tableContainerRef}
          className="max-h-[640px] overflow-y-auto divide-y divide-white/[0.04]"
        >
          {isLoading ? (
            <div className="py-24 text-center text-slate-400 font-mono text-sm flex flex-col items-center gap-2">
              <div className="w-6 h-6 rounded-full border-2 border-token-cyan border-t-transparent animate-spin" />
              <span>Scanning universe for 3–10% monthly swing signals...</span>
            </div>
          ) : rows.length === 0 ? (
            <div className="py-24 text-center text-slate-400 font-mono text-sm">
              No swing candidates match active strategy or filter criteria.
            </div>
          ) : (
            <div
              style={{
                height: `${rowVirtualizer.getTotalSize()}px`,
                width: '100%',
                position: 'relative',
              }}
            >
              {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                const row = rows[virtualRow.index];
                return (
                  <div
                    key={row.id}
                    onClick={() => onSelectCandidate(row.original.ticker)}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: `${virtualRow.size}px`,
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                    className="flex items-center px-4 hover:bg-surface-elevated/60 transition-colors cursor-pointer group"
                  >
                    {row.getVisibleCells().map((cell) => (
                      <div
                        key={cell.id}
                        className={`${
                          cell.column.id === 'ticker'
                            ? 'w-1/5'
                            : cell.column.id === 'price'
                            ? 'w-[14%] justify-end text-right'
                            : cell.column.id === 'strategy'
                            ? 'w-[14%]'
                            : cell.column.id === 'confidence_score'
                            ? 'w-[10%] justify-center text-center'
                            : cell.column.id === 'target_return_pct'
                            ? 'w-[10%] justify-end text-right'
                            : cell.column.id === 'setup'
                            ? 'w-[14%]'
                            : cell.column.id === 'risk_reward_ratio'
                            ? 'w-[9%]'
                            : cell.column.id === 'catalyst'
                            ? 'w-[11%]'
                            : 'w-[7%] justify-end'
                        }`}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
