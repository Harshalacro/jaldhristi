import { href } from '../lib/router';

/**
 * About JalDrishti: each capability, how it works, and where to see it, followed
 * by the data sources and the known limits.
 */

const hi = (lang) => (lang === 'hi' ? 'font-devanagari' : '');

const ROWS = [
  {
    req: ['Street-level waterlogging detection', 'गली-स्तरीय जलभराव पहचान'],
    how: [
      '800 m grid per city: DEM low ground, sink depth and D8 flow accumulation; OpenStreetMap drains, roads and built-up land; hourly rain on a 3×3 lattice; an hour-by-hour ponding model',
      'प्रति शहर 800 मी ग्रिड: DEM से निचली भूमि, गड्ढे व जल-प्रवाह संचय; OSM से नालियाँ, सड़कें व निर्मित क्षेत्र; प्रति घंटा वर्षा पर जलभराव मॉडल',
    ],
    link: ['/hotspots/mumbai', 'Street-level hotspots'],
  },
  {
    req: ['Drivers of flood risk and scenarios', 'बाढ़ जोखिम के कारक व परिदृश्य'],
    how: [
      'Ten named factors with weights and point contributions; what-if simulator re-scores real inputs; design-storm and drain-capacity controls on the hotspot map',
      'भार व योगदान सहित दस नामित कारक; क्या-यदि सिम्युलेटर; हॉटस्पॉट नक्शे पर डिज़ाइन तूफ़ान व नाली क्षमता नियंत्रण',
    ],
    link: ['/location/mumbai', 'Location assessment'],
  },
  {
    req: ['Nationwide risk monitoring', 'राष्ट्रव्यापी जोखिम निगरानी'],
    how: [
      '112 towns in all 36 states/UTs scored against IMD colour tiers; live CWC gauges above danger and NDMA/IMD alerts raise scores; anomaly detection flags unusual combinations',
      'सभी 36 राज्यों/केंद्र शासित प्रदेशों में 112 शहर IMD रंग स्तरों पर; CWC गेज व आधिकारिक चेतावनियाँ स्कोर बढ़ाती हैं; असामान्यता पहचान',
    ],
    link: ['/', 'Overview'],
  },
  {
    req: ['Forecasts: how risk evolves', 'पूर्वानुमान: जोखिम कैसे बदलेगा'],
    how: [
      '72 h town trajectory with ensemble band; 48 h hotspot timeline with play-through; Chronos-Bolt (Hugging Face) forecasts each river gauge 48 h ahead, including time to cross the danger mark',
      'एन्सेम्बल पट्टी सहित 72 घंटे का प्रक्षेपवक्र; 48 घंटे हॉटस्पॉट समयरेखा; Chronos-Bolt से नदी गेज का 48 घंटे पूर्वानुमान',
    ],
    link: ['/rivers', 'Rivers'],
  },
  {
    req: ['Response prioritisation by impact', 'प्रभाव अनुसार प्रतिक्रिया प्राथमिकता'],
    how: [
      'Hotspot priority list = water risk × exposure (urban density, hospitals, schools, road underpasses) with specific actions; state monitor ranks states by gauges above danger and people at risk',
      'हॉटस्पॉट प्राथमिकता = जलभराव जोखिम × प्रभाव (घनत्व, अस्पताल, स्कूल, अंडरपास) व विशिष्ट कार्रवाई; राज्य निगरानी',
    ],
    link: ['/states', 'State monitor'],
  },
  {
    req: ['Confidence and uncertainty', 'विश्वसनीयता व अनिश्चितता'],
    how: [
      'Confidence badge with written reasons (ensemble spread, baseline, gauge availability, model agreement); uncertainty bands on every forecast; hotspot ponding re-run at 60 % and 140 % rain',
      'लिखित कारणों सहित विश्वसनीयता; हर पूर्वानुमान पर अनिश्चितता पट्टी; वर्षा 60% व 140% पर पुनः गणना',
    ],
    link: ['/location/patna', 'Confidence detail'],
  },
  {
    req: ['Explainable assessments', 'व्याख्या योग्य आकलन'],
    how: [
      'Plain-language narrative in English and Hindi generated from the actual contributions; model attribution (log-odds); similar past floods found by k-NN over 2,699 real days',
      'वास्तविक योगदान से हिंदी व अंग्रेज़ी व्याख्या; मॉडल गुणारोपण; 2,699 वास्तविक दिनों पर k-NN से मिलती-जुलती पिछली बाढ़',
    ],
    link: ['/location/patna', 'Explanation'],
  },
  {
    req: ['Continuous live updates', 'निरंतर लाइव अद्यतन'],
    how: [
      'Weather re-ingested every 90 min and on demand with a change report; all 1,036 CWC gauges re-read every 15 min, re-scoring towns when a nearby river crosses a mark; Time Machine runs the same engine on any past date',
      'हर 90 मिनट व माँग पर मौसम पुनः गणना; सभी 1,036 CWC गेज हर 15 मिनट; टाइम मशीन',
    ],
    link: ['/time-machine', 'Time Machine'],
  },
  {
    req: ['Preparedness and decision support', 'तैयारी व निर्णय-सहायता'],
    how: [
      'NDMA-aligned actions per tier; bilingual public advisory + SMS draft; grounded AI copilot for questions in English or Hindi',
      'NDMA अनुरूप कार्रवाई; द्विभाषी जन-सलाह व SMS; हिंदी/अंग्रेज़ी में प्रश्नों हेतु एआई सहायक',
    ],
    link: ['/alerts', 'Official alerts'],
  },
];

const LIMITS = [
  ['The DEM is 90 m: individual underpasses and kerb-level dips are below its resolution.', 'DEM 90 मी है: अलग-अलग अंडरपास इसकी सूक्ष्मता से छोटे हैं।'],
  ['No open storm-sewer network data exists for Indian cities, so drainage capacity is estimated from mapped drains and land use.', 'भारतीय शहरों के सीवर नेटवर्क के खुले आँकड़े नहीं हैं; नाली क्षमता अनुमानित है।'],
  ['CWC data comes from the endpoints behind its flood-forecast portal, not a documented public API, and may change.', 'CWC आँकड़े उसके पोर्टल के आंतरिक एंडपॉइंट से हैं, प्रलेखित API से नहीं।'],
  ['IMD APIs require IP whitelisting; IMD warnings are read through NDMA SACHET instead.', 'IMD API हेतु IP अनुमति आवश्यक; IMD चेतावनियाँ SACHET से पढ़ी जाती हैं।'],
  ['Historical replays are model-only: past gauge readings and alerts are not archived.', 'ऐतिहासिक पुनरावृत्ति केवल मॉडल आधारित है।'],
];

export default function AboutPage({ lang }) {
  return (
    <div id="main-content" className="mx-auto w-full max-w-[1200px] space-y-5 p-4">
      <div className="border-b-2 border-saffron-500 pb-3">
        <h1 className={`text-2xl font-extrabold tracking-tight text-chakra-500 ${hi(lang)}`}>
          {lang === 'hi' ? 'जलदृष्टि के बारे में' : 'About JalDrishti'}
        </h1>
        <p className={`mt-1 text-[12.5px] text-ink-400 ${hi(lang)}`}>
          {lang === 'hi'
            ? 'अति-स्थानीय शहरी बाढ़ पूर्वानुमान एवं प्रतिक्रिया मंच — इसकी क्षमताएँ, कार्यप्रणाली, आँकड़ा स्रोत और सीमाएँ'
            : 'Hyperlocal flood prediction and response platform — its capabilities, how they work, the data behind them, and their limits'}
        </p>
      </div>

      <div className="panel overflow-x-auto">
        <table className="w-full text-left text-[12.5px]">
          <thead className="bg-chakra-500 text-[11px] uppercase tracking-wider text-white">
            <tr>
              <th className="px-4 py-3">{lang === 'hi' ? 'क्षमता' : 'Capability'}</th>
              <th className="px-4 py-3">{lang === 'hi' ? 'यह कैसे काम करता है' : 'How it works'}</th>
              <th className="px-4 py-3">{lang === 'hi' ? 'देखें' : 'Explore'}</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r, i) => (
              <tr key={i} className="border-t border-ink-800 align-top even:bg-ink-850">
                <td className={`w-[30%] px-4 py-3 font-semibold text-chakra-500 ${hi(lang)}`}>{lang === 'hi' ? r.req[1] : r.req[0]}</td>
                <td className={`px-4 py-3 text-ink-200 ${hi(lang)}`}>{lang === 'hi' ? r.how[1] : r.how[0]}</td>
                <td className="whitespace-nowrap px-4 py-3">
                  <a href={href(r.link[0])} className="font-bold text-saffron-300 hover:underline">{r.link[1]} →</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="panel p-4">
          <h2 className={`text-[13px] font-bold uppercase tracking-wider text-chakra-500 ${hi(lang)}`}>{lang === 'hi' ? 'आँकड़ा स्रोत' : 'Data sources'}</h2>
          <ul className="mt-2 space-y-1.5 text-[12px] text-ink-200">
            <li>• Central Water Commission — 1,036 river gauges, hourly levels, danger marks</li>
            <li>• NDMA SACHET — live CAP alerts from IMD, CWC and State DMAs</li>
            <li>• Open-Meteo — hourly rainfall and soil moisture; GloFAS v4 river discharge (1994–2024 climatology)</li>
            <li>• Copernicus DEM GLO-90 — elevation for terrain and hotspots</li>
            <li>• OpenStreetMap — drains, roads, land use, hospitals, schools, underpasses</li>
            <li>• Hugging Face amazon/chronos-bolt-small — river-level forecasting</li>
            <li>• Natural Earth — river network geometry</li>
          </ul>
        </section>
        <section className="panel p-4">
          <h2 className={`text-[13px] font-bold uppercase tracking-wider text-chakra-500 ${hi(lang)}`}>{lang === 'hi' ? 'ज्ञात सीमाएँ' : 'Known limitations'}</h2>
          <ul className="mt-2 space-y-1.5">
            {LIMITS.map((l) => (
              <li key={l[0]} className={`text-[12px] text-ink-300 ${hi(lang)}`}>• {lang === 'hi' ? l[1] : l[0]}</li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
