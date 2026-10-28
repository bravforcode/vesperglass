import { useEffect, useState, useCallback } from 'react';
import { Header } from './components/Header';
import { MarketPulse } from './components/MarketPulse';
import { FilterRibbon } from './components/FilterRibbon';
import { ScreenerTable } from './components/ScreenerTable';
import { StockModal } from './components/StockModal';
import { Candidate, MarketPulse as MarketPulseType } from './types';

export function App() {
  const [pulse, setPulse] = useState<MarketPulseType | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

  // Filters
  const [selectedStrategy, setSelectedStrategy] = useState<string>('all');
  const [selectedSector, setSelectedSector] = useState<string>('all');
  const [minReturn, setMinReturn] = useState<number>(0);
  const [marketCap, setMarketCap] = useState<string>('all');
  const [minRr, setMinRr] = useState<number>(2.0);
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Selected Stock for Deep Dive Modal
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);

  const fetchPulse = useCallback(() => {
    fetch('/api/market-pulse')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) setPulse(data);
      })
      .catch((err) => console.error('Failed to load market pulse:', err));
  }, []);

  const fetchCandidates = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams();
    if (selectedStrategy && selectedStrategy !== 'all') {
      params.append('strategy', selectedStrategy);
    }
    if (selectedSector && selectedSector !== 'all') {
      params.append('sector', selectedSector);
    }
    if (minReturn > 0) {
      params.append('min_return', minReturn.toString());
    }
    if (marketCap && marketCap !== 'all') {
      params.append('market_cap', marketCap);
    }
    if (minRr > 0) {
      params.append('min_rr', minRr.toString());
    }
    if (searchQuery) {
      params.append('search', searchQuery);
    }
    params.append('limit', '100');

    fetch(`/api/screen?${params.toString()}`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data: Candidate[]) => {
        setCandidates(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to load screener candidates:', err);
        setLoading(false);
      });
  }, [selectedStrategy, selectedSector, minReturn, marketCap, minRr, searchQuery]);

  useEffect(() => {
    fetchPulse();
  }, [fetchPulse]);

  useEffect(() => {
    fetchCandidates();
  }, [fetchCandidates]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    fetch('/api/scan/refresh', { method: 'POST' })
      .then(() => {
        fetchPulse();
        fetchCandidates();
      })
      .finally(() => {
        setTimeout(() => setIsRefreshing(false), 500);
      });
  };

  return (
    <div className="min-h-screen bg-[#07090E] text-slate-100 flex flex-col font-sans">
      {/* Top Header & Pulse Bar */}
      <Header
        pulse={pulse}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        onRefresh={handleRefresh}
        isRefreshing={isRefreshing}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Bento Grid Telemetry Cards */}
        <MarketPulse
          pulse={pulse}
          onSelectTopOpportunity={(ticker) => setSelectedTicker(ticker)}
        />

        {/* Multi-Criteria Filter Ribbon */}
        <FilterRibbon
          selectedStrategy={selectedStrategy}
          onStrategyChange={setSelectedStrategy}
          selectedSector={selectedSector}
          onSectorChange={setSelectedSector}
          minReturn={minReturn}
          onMinReturnChange={setMinReturn}
          marketCap={marketCap}
          onMarketCapChange={setMarketCap}
          minRr={minRr}
          onMinRrChange={setMinRr}
          totalFilteredCount={candidates.length}
        />

        {/* Screener Data Grid */}
        <ScreenerTable
          candidates={candidates}
          onSelectCandidate={(ticker) => setSelectedTicker(ticker)}
          isLoading={loading}
        />
      </main>

      {/* Footer */}
      <footer className="border-t border-white/[0.06] bg-[#07090E] py-6 text-xs text-slate-500 font-mono">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span>STOCKNOMIST v1.0</span>
            <span>•</span>
            <span className="text-token-cyan">Tokenomist Dark UI</span>
            <span>•</span>
            <span>S&P 500 / Nasdaq 100 / Russell 1000</span>
          </div>
          <div className="flex items-center gap-4 text-slate-400">
            <span className="text-token-emerald">● Zero External API Spend</span>
            <span>RAM &lt; 250MB</span>
            <span>Latency &lt; 50ms</span>
          </div>
        </div>
      </footer>

      {/* Comprehensive Stock Deep-Dive Modal */}
      {selectedTicker && (
        <StockModal
          ticker={selectedTicker}
          onClose={() => setSelectedTicker(null)}
        />
      )}
    </div>
  );
}

export default App;
