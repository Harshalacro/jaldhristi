import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from './lib/api';
import { t } from './lib/i18n';
import { go, href, useRoute } from './lib/router';
import { AlertTicker, AshokaChakra, Footer, Masthead } from './components/Chrome';
import Copilot from './components/Copilot';
import { StationModal } from './components/Official';
import SearchBox from './components/SearchBox';
import SystemDialog from './components/SystemDialog';
import AboutPage from './pages/AboutPage';
import HotspotsPage from './pages/HotspotsPage';
import LocationPage from './pages/LocationPage';
import Overview from './pages/Overview';
import { OfficialPage, StateMonitor, TimeMachine } from './pages/Pages';
import RiversPage from './pages/RiversPage';

/**
 * Application shell: shared data, chrome and routing.
 *
 * Each view is its own page with its own URL (see lib/router.js). The shell loads
 * what several pages share - the national snapshot, the location list, CWC gauges
 * and official alerts - polls it so pages stay live, and owns the global overlays
 * (station hydrograph, copilot, model card).
 */

const POLL_MS = 60_000;

const NAV = [
  { route: 'overview', to: '/', en: 'Overview', hi: 'अवलोकन', icon: '◉', match: ['overview', 'state'] },
  { route: 'hotspots', to: '/hotspots', en: 'City Hotspots', hi: 'शहर हॉटस्पॉट', icon: '▦', match: ['hotspots'] },
  { route: 'rivers', to: '/rivers', en: 'Rivers', hi: 'नदियाँ', icon: '≋', match: ['rivers'] },
  { route: 'alerts', to: '/alerts', en: 'Official Alerts', hi: 'आधिकारिक चेतावनियाँ', icon: '⛨', match: ['alerts'] },
  { route: 'states', to: '/states', en: 'State Monitor', hi: 'राज्य निगरानी', icon: '▤', match: ['states'] },
  { route: 'timemachine', to: '/time-machine', en: 'Time Machine', hi: 'टाइम मशीन', icon: '⟲', match: ['timemachine'] },
  { route: 'about', to: '/about', en: 'About JalDrishti', hi: 'जलदृष्टि परिचय', icon: 'ⓘ', match: ['about'] },
];

function useStickyLang() {
  const [lang, setLang] = useState(() => {
    try {
      const saved = localStorage.getItem('jd.lang');
      if (saved === 'en' || saved === 'hi') return saved;
    } catch {
      /* storage blocked */
    }
    return 'en';
  });
  useEffect(() => {
    try {
      localStorage.setItem('jd.lang', lang);
    } catch {
      /* non-fatal */
    }
    document.documentElement.lang = lang;
  }, [lang]);
  return [lang, setLang];
}

export default function App() {
  const [lang, setLang] = useStickyLang();
  const route = useRoute();

  const [system, setSystem] = useState(null);
  const [country, setCountry] = useState(null);
  const [locations, setLocations] = useState([]);
  const [gauges, setGauges] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [replayDate, setReplayDate] = useState(null);
  const [stationCode, setStationCode] = useState(null);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [systemOpen, setSystemOpen] = useState(false);
  const pollRef = useRef(null);

  const locationsById = useMemo(() => Object.fromEntries(locations.map((l) => [l.id, l])), [locations]);

  const loadCore = useCallback(
    async ({ quiet = false } = {}) => {
      if (!quiet) setStatus((s) => (s === 'ready' ? s : 'loading'));
      try {
        const [summary, locs] = await Promise.all([api.countrySummary(replayDate), api.locations(replayDate)]);
        setCountry(summary);
        setLocations(locs.locations);
        setStatus('ready');
        setError(null);
      } catch (err) {
        if (err instanceof ApiError && err.warming) setStatus('warming');
        else {
          setStatus('error');
          setError(err.message);
        }
      }
    },
    [replayDate],
  );

  useEffect(() => {
    loadCore();
    api.system().then(setSystem).catch(() => {});
  }, [loadCore]);

  useEffect(() => {
    clearInterval(pollRef.current);
    if (replayDate) return undefined;
    pollRef.current = setInterval(() => loadCore({ quiet: true }), status === 'warming' ? 5000 : POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [loadCore, status, replayDate]);

  useEffect(() => {
    if (replayDate) return;
    api.officialStations(false).then((d) => setGauges(d.stations)).catch(() => {});
    api.officialAlerts(true).then((d) => setAlerts(d.alerts)).catch(() => {});
  }, [replayDate, country?.meta?.run_id]);

  const onRefresh = useCallback(async () => {
    if (replayDate) {
      setReplayDate(null);
      return;
    }
    setRefreshing(true);
    try {
      await api.refresh();
      await loadCore({ quiet: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setRefreshing(false);
    }
  }, [loadCore, replayDate]);

  const startReplay = useCallback(async (date) => {
    await api.countrySummary(date);
    setReplayDate(date);
    go('/');
  }, []);

  const openLocation = useCallback((id) => go(`/location/${id}`), []);
  const hi = lang === 'hi' ? 'font-devanagari' : '';

  const chromeProps = {
    lang,
    onLangChange: setLang,
    refreshing: refreshing || country?.meta?.refreshing,
    onRefresh,
    onOpenSystem: () => setSystemOpen(true),
    onOpenCopilot: () => setCopilotOpen(true),
  };

  if (status === 'error' || status === 'loading' || status === 'warming') {
    return (
      <div className="flex h-full flex-col">
        <Masthead {...chromeProps} meta={null} refreshing={status !== 'error'} onRefresh={() => loadCore()} />
        <main className="grid flex-1 place-items-center p-6">
          {status === 'error' ? (
            <div className="panel max-w-md p-5 text-center">
              <h2 className={`mb-2 text-sm font-bold text-risk-orange ${hi}`}>{t(lang, 'errorTitle')}</h2>
              <p className="mb-4 text-[12px] text-ink-300">{error}</p>
              <code className="block rounded bg-ink-850 p-3 text-left font-mono text-[11px] text-chakra-500">
                cd backend
                <br />
                python -m uvicorn app.main:app --port 8000
              </code>
              <button type="button" className="btn btn-primary mt-4 w-full" onClick={() => loadCore()}>
                {t(lang, 'retry')}
              </button>
            </div>
          ) : (
            <div className="max-w-sm text-center">
              <span className="mx-auto mb-4 block w-fit text-chakra-500">
                <AshokaChakra size={52} spinning />
              </span>
              <p className={`text-[13px] text-ink-300 ${hi}`}>{status === 'warming' ? t(lang, 'warming') : t(lang, 'loading')}</p>
            </div>
          )}
        </main>
      </div>
    );
  }

  let page;
  switch (route.name) {
    case 'overview':
    case 'state':
      page = (
        <Overview
          lang={lang}
          country={country}
          locations={locations}
          selectedState={route.params.state ?? null}
          replayDate={replayDate}
          gauges={gauges}
          alerts={alerts}
          onOpenStation={setStationCode}
        />
      );
      break;
    case 'location':
      page = <LocationPage lang={lang} id={route.params.id} replayDate={replayDate} onOpenStation={setStationCode} locationsById={locationsById} />;
      break;
    case 'hotspots':
      page = <HotspotsPage lang={lang} id={route.params.id} locations={locations} />;
      break;
    case 'rivers':
      page = <RiversPage lang={lang} river={route.params.river} onOpenStation={setStationCode} />;
      break;
    case 'alerts':
      page = <OfficialPage lang={lang} onOpenStation={setStationCode} />;
      break;
    case 'states':
      page = (
        <StateMonitor
          lang={lang}
          country={country}
          locations={locations}
          alerts={alerts}
          replayDate={replayDate}
          onViewState={(name) => go(`/state/${name}`)}
          onOpenLocation={openLocation}
          onOpenStation={setStationCode}
        />
      );
      break;
    case 'timemachine':
      page = <TimeMachine lang={lang} replayDate={replayDate} onReplay={startReplay} onExit={() => setReplayDate(null)} />;
      break;
    case 'about':
      page = <AboutPage lang={lang} />;
      break;
    default:
      page = (
        <div className="grid flex-1 place-items-center p-10 text-center">
          <div>
            <p className="text-lg font-bold text-chakra-500">Page not found</p>
            <a href={href('/')} className="text-saffron-300 hover:underline">← Overview</a>
          </div>
        </div>
      );
  }

  // The overview is a fixed-height dashboard; every other page scrolls as a document.
  const scrollingPage = !['overview', 'state'].includes(route.name);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Masthead {...chromeProps} meta={country?.meta}>
        <SearchBox lang={lang} locations={locations} onSelect={openLocation} />
      </Masthead>

      <nav className="relative z-10 shrink-0 border-b border-ink-700 bg-white" aria-label="Main">
        <div className="flex items-stretch gap-0.5 overflow-x-auto px-3 scrollbar-thin">
          {NAV.map((n) => {
            const active = n.match.includes(route.name);
            return (
              <a
                key={n.route}
                href={href(n.to)}
                aria-current={active ? 'page' : undefined}
                className={`flex shrink-0 items-center gap-1.5 border-b-[3px] px-3 py-2.5 text-[12.5px] font-bold transition ${
                  active ? 'border-saffron-500 text-chakra-500' : 'border-transparent text-ink-400 hover:border-saffron-500/40 hover:text-chakra-500'
                } ${hi}`}
              >
                <span aria-hidden="true" className="text-saffron-500">{n.icon}</span>
                {lang === 'hi' ? n.hi : n.en}
              </a>
            );
          })}
        </div>
      </nav>

      {replayDate ? (
        <div className="relative z-10 flex shrink-0 flex-wrap items-center gap-3 bg-chakra-500 px-4 py-2 text-white">
          <span className="rounded bg-saffron-500 px-2 py-0.5 text-[10.5px] font-extrabold uppercase tracking-wider">
            {lang === 'hi' ? 'ऐतिहासिक पुनरावृत्ति' : 'Historical replay'}
          </span>
          <span className="font-mono text-[13px] font-bold">
            {new Date(replayDate).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'long', year: 'numeric' })}
          </span>
          <button type="button" onClick={() => setReplayDate(null)} className="ml-auto rounded-md bg-white px-3 py-1 text-[12px] font-bold text-chakra-500">
            {lang === 'hi' ? 'लाइव पर लौटें' : 'Back to live'}
          </button>
        </div>
      ) : (
        <AlertTicker lang={lang} worst={country?.worst ?? []} summary={country?.summary} />
      )}

      <div className="shrink-0 border-b border-ink-700 bg-white px-3 py-2 md:hidden">
        <SearchBox lang={lang} locations={locations} onSelect={openLocation} />
      </div>

      {scrollingPage ? <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">{page}</div> : page}

      <Footer lang={lang} system={system} meta={country?.meta} />

      <StationModal lang={lang} code={stationCode} onClose={() => setStationCode(null)} />
      <Copilot lang={lang} open={copilotOpen} onClose={() => setCopilotOpen(false)} onSelectLocation={openLocation} locations={locations} />
      <SystemDialog lang={lang} system={system} open={systemOpen} onClose={() => setSystemOpen(false)} />
    </div>
  );
}
