import { createContext, useContext, useEffect, useState } from "react";

const DICT = {
  en: {
    appName: "Manganese Horizon",
    tagline: "Reserve confidence · Shortfall forecasting · Corrective actions",
    nav_overview: "Command Centre", nav_reserves: "Reserve Confidence", nav_forecast: "Shortfall Forecast",
    nav_actions: "Corrective Actions", nav_scenarios: "What-if Scenarios", nav_integrity: "Data & Integrity", nav_report: "Executive Brief",
    banner_synthetic: "DEMO DATA — production, borehole and the model's satellite values are simulated; the Sentinel-2 imagery and the real-data check on the Reserves page use real satellite data. Outputs demonstrate the method and are not validated for MOIL operations.",
    banner_mixed: "MIXED DATA — uploaded real records are combined with simulated records. Outputs are not validated.",
    offline: "Offline — showing cached data", online: "Online", pending_sync: "decisions waiting to sync",
    guided_demo: "Guided demo", next: "Next", back: "Back", close: "Close",
    risk_LOW: "Low", risk_MODERATE: "Moderate", risk_HIGH: "High", risk_CRITICAL: "Critical",
    tag_OBSERVED: "Observed", tag_FORECAST: "Forecast", tag_MODEL_INFERENCE: "Model inference", tag_SCENARIO: "Scenario",
    next_month: "Next month", target: "Target", median: "Median (P50)", range: "P10–P90 range",
    achievement_prob: "Chance of meeting target", deficit: "Expected deficit", mines_at_risk: "Mines at risk",
    mitigated: "Covered by action plan", unmitigated: "Not covered", drill_targets: "Drill targets",
    risk_drivers: "What is pulling the forecast down", positive_drivers: "What is holding it up",
    approve: "Approve", reject: "Reject", defer: "Defer", decided_by: "Your name / role",
    prospectivity_note: "Prospectivity ranks where to drill next. It is not a reserve estimate (UNFC/JORC/CRIRSCO).",
    satellite_note: "Satellites see the surface only; they cannot detect ore underground.",
    loading: "Loading…", training: "Models are training on first start (about 30 s)…",
    mine: "Mine", month: "Month", priority: "Priority", tonnes: "Tonnes", action: "Action", cost: "Cost",
    language: "Language",
  },
  hi: {
    appName: "मैंगनीज़ होराइज़न",
    tagline: "भंडार विश्वसनीयता · उत्पादन कमी पूर्वानुमान · सुधारात्मक कदम",
    nav_overview: "कमांड सेंटर", nav_reserves: "भंडार विश्वसनीयता", nav_forecast: "कमी पूर्वानुमान",
    nav_actions: "सुधारात्मक कदम", nav_scenarios: "क्या-अगर परिदृश्य", nav_integrity: "डेटा व सत्यनिष्ठा", nav_report: "कार्यकारी सारांश",
    banner_synthetic: "डेमो डेटा — उत्पादन, बोरहोल और मॉडल के उपग्रह मान सिम्युलेटेड हैं; भंडार पृष्ठ की Sentinel-2 छवि और वास्तविक-डेटा जाँच असली उपग्रह डेटा पर आधारित हैं। परिणाम केवल पद्धति दिखाते हैं, MOIL संचालन हेतु सत्यापित नहीं हैं।",
    banner_mixed: "मिश्रित डेटा — अपलोड किए गए वास्तविक रिकॉर्ड सिम्युलेटेड रिकॉर्ड के साथ हैं। परिणाम सत्यापित नहीं हैं।",
    offline: "ऑफ़लाइन — संग्रहीत डेटा दिखाया जा रहा है", online: "ऑनलाइन", pending_sync: "निर्णय सिंक होने बाकी",
    guided_demo: "निर्देशित डेमो", next: "आगे", back: "पीछे", close: "बंद करें",
    risk_LOW: "कम", risk_MODERATE: "मध्यम", risk_HIGH: "उच्च", risk_CRITICAL: "गंभीर",
    tag_OBSERVED: "प्रेक्षित", tag_FORECAST: "पूर्वानुमान", tag_MODEL_INFERENCE: "मॉडल अनुमान", tag_SCENARIO: "परिदृश्य",
    next_month: "अगला माह", target: "लक्ष्य", median: "माध्यिका (P50)", range: "P10–P90 सीमा",
    achievement_prob: "लक्ष्य प्राप्ति की संभावना", deficit: "अपेक्षित कमी", mines_at_risk: "जोखिम में खदानें",
    mitigated: "कार्य योजना से पूर्ति", unmitigated: "अपूर्ण", drill_targets: "ड्रिलिंग लक्ष्य",
    risk_drivers: "पूर्वानुमान को नीचे खींचने वाले कारक", positive_drivers: "सहायक कारक",
    approve: "स्वीकृत", reject: "अस्वीकृत", defer: "स्थगित", decided_by: "आपका नाम / पद",
    prospectivity_note: "संभाव्यता बताती है कि आगे कहाँ ड्रिल करें। यह भंडार अनुमान नहीं है (UNFC/JORC/CRIRSCO)।",
    satellite_note: "उपग्रह केवल सतह देखते हैं; वे भूमिगत अयस्क नहीं पहचान सकते।",
    loading: "लोड हो रहा है…", training: "पहली बार मॉडल प्रशिक्षित हो रहे हैं (लगभग 30 सेकंड)…",
    mine: "खदान", month: "माह", priority: "प्राथमिकता", tonnes: "टन", action: "कदम", cost: "लागत",
    language: "भाषा",
  },
  mr: {
    appName: "मँगनीज होरायझन",
    tagline: "साठा विश्वासार्हता · उत्पादन तूट अंदाज · सुधारात्मक उपाय",
    nav_overview: "कमांड सेंटर", nav_reserves: "साठा विश्वासार्हता", nav_forecast: "तूट अंदाज",
    nav_actions: "सुधारात्मक उपाय", nav_scenarios: "जर-तर परिस्थिती", nav_integrity: "डेटा व सचोटी", nav_report: "कार्यकारी सारांश",
    banner_synthetic: "डेमो डेटा — उत्पादन, बोअरहोल आणि मॉडेलची उपग्रह मूल्ये सिम्युलेटेड आहेत; साठा पानावरील Sentinel-2 प्रतिमा आणि खऱ्या डेटाची तपासणी खऱ्या उपग्रह डेटावर आधारित आहे. निकाल फक्त पद्धत दाखवतात, MOIL कामकाजासाठी प्रमाणित नाहीत.",
    banner_mixed: "मिश्र डेटा — अपलोड केलेल्या खऱ्या नोंदी सिम्युलेटेड नोंदींसोबत आहेत. निकाल प्रमाणित नाहीत.",
    offline: "ऑफलाइन — जतन केलेला डेटा दाखवत आहे", online: "ऑनलाइन", pending_sync: "निर्णय सिंक व्हायचे बाकी",
    guided_demo: "मार्गदर्शित डेमो", next: "पुढे", back: "मागे", close: "बंद करा",
    risk_LOW: "कमी", risk_MODERATE: "मध्यम", risk_HIGH: "जास्त", risk_CRITICAL: "गंभीर",
    tag_OBSERVED: "निरीक्षित", tag_FORECAST: "अंदाज", tag_MODEL_INFERENCE: "मॉडेल अनुमान", tag_SCENARIO: "परिस्थिती",
    next_month: "पुढील महिना", target: "लक्ष्य", median: "मध्यक (P50)", range: "P10–P90 श्रेणी",
    achievement_prob: "लक्ष्य गाठण्याची शक्यता", deficit: "अपेक्षित तूट", mines_at_risk: "धोक्यातील खाणी",
    mitigated: "कृती आराखड्याने भरपाई", unmitigated: "न भरलेली", drill_targets: "ड्रिलिंग लक्ष्ये",
    risk_drivers: "अंदाज खाली ओढणारे घटक", positive_drivers: "आधार देणारे घटक",
    approve: "मंजूर", reject: "नामंजूर", defer: "पुढे ढकला", decided_by: "आपले नाव / पद",
    prospectivity_note: "संभाव्यता पुढे कुठे ड्रिल करावे हे सुचवते. हा साठ्याचा अंदाज नाही (UNFC/JORC/CRIRSCO).",
    satellite_note: "उपग्रह फक्त पृष्ठभाग पाहतात; ते जमिनीखालील खनिज ओळखू शकत नाहीत.",
    loading: "लोड होत आहे…", training: "पहिल्यांदा मॉडेल प्रशिक्षित होत आहेत (सुमारे 30 सेकंद)…",
    mine: "खाण", month: "महिना", priority: "प्राधान्य", tonnes: "टन", action: "उपाय", cost: "खर्च",
    language: "भाषा",
  },
};

export const LANGS = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "mr", label: "मराठी" },
];

const Ctx = createContext({ lang: "en", t: (k) => k, setLang: () => {} });

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(() => {
    try { return localStorage.getItem("mh-lang") || "en"; } catch { return "en"; }
  });
  useEffect(() => {
    document.documentElement.lang = lang;
    try { localStorage.setItem("mh-lang", lang); } catch { /* storage unavailable */ }
  }, [lang]);
  const t = (k) => DICT[lang]?.[k] ?? DICT.en[k] ?? k;
  return <Ctx.Provider value={{ lang, setLang, t }}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);
