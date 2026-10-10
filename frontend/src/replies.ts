import type { Claim, Status, Verdict } from "./types";

export type Lang = "en" | "hi" | "te";

export const LANGS: { id: Lang; label: string }[] = [
  { id: "en", label: "English" },
  { id: "hi", label: "हिन्दी" },
  { id: "te", label: "తెలుగు" },
];

type X = { g: string; amt: string; stmt: string; ref: string; when: string };

const GREET: Record<Lang, (n: string) => string> = {
  en: (n) => (n ? `Hi ${n},` : "Hi,"),
  hi: (n) => (n ? `नमस्ते ${n},` : "नमस्ते,"),
  te: (n) => (n ? `నమస్తే ${n},` : "నమస్తే,"),
};

const T: Record<Lang, Record<Status, (x: X) => string>> = {
  en: {
    "Verified": (x) =>
      `${x.g} thank you! We have received your payment of ${x.amt}${x.ref ? ` (ref ${x.ref})` : ""}. Everything is confirmed.`,
    "Likely match": (x) =>
      `${x.g} we found a payment that looks like yours (${x.amt}${x.when ? `, ${x.when}` : ""}). Please reply with the reference number from your bank app so we can confirm it.`,
    "Contradicted": (x) =>
      x.stmt
        ? `${x.g} thanks for your payment details. Reference ${x.ref} appears in our account for ₹${x.stmt}, but your screenshot shows ${x.amt}. Could you please check and share the correct screenshot, or the difference payment?`
        : `${x.g} thanks for your payment details. We found reference ${x.ref}, but some details (such as the amount or date) differ from your screenshot. Could you please recheck your bank app and share the correct details?`,
    "Not found": (x) =>
      `${x.g} thank you for sending your payment confirmation. We checked our account and could not find a credit${x.ref ? ` with reference ${x.ref}` : ""} for ${x.amt}. Could you please share the UTR from your bank app's transaction history, or send it again once the payment shows as completed?`,
    "Duplicate": (x) =>
      `${x.g} the same payment${x.ref ? ` reference ${x.ref}` : ""} was also submitted for another payment. Please share your own transaction details so we can confirm your payment.`,
    "Can't verify yet": (x) =>
      `${x.g} thanks, we have received your payment details. Our statement does not cover that time yet, so we will confirm after our next update. No action needed from you right now.`,
  },
  hi: {
    "Verified": (x) =>
      `${x.g} आपका ${x.amt} का भुगतान${x.ref ? ` (रेफरेंस ${x.ref})` : ""} हमारे खाते में मिल गया है। धन्यवाद!`,
    "Likely match": (x) =>
      `${x.g} हमें आपके भुगतान जैसा एक भुगतान मिला है (${x.amt}${x.when ? `, ${x.when}` : ""})। कृपया अपने बैंक ऐप से रेफरेंस नंबर भेज दें ताकि हम इसे पक्का कर सकें।`,
    "Contradicted": (x) =>
      x.stmt
        ? `${x.g} भुगतान का विवरण भेजने के लिए धन्यवाद। रेफरेंस ${x.ref} हमारे खाते में ₹${x.stmt} दिख रहा है, जबकि आपके स्क्रीनशॉट में ${x.amt} है। कृपया जाँचकर सही स्क्रीनशॉट या बाकी रकम भेज दें।`
        : `${x.g} भुगतान का विवरण भेजने के लिए धन्यवाद। हमें रेफरेंस ${x.ref} मिला है, लेकिन कुछ विवरण (जैसे रकम या तारीख़) आपके स्क्रीनशॉट से मेल नहीं खा रहे। कृपया अपने बैंक ऐप में दोबारा देखकर सही विवरण भेजें।`,
    "Not found": (x) =>
      `${x.g} भुगतान की जानकारी भेजने के लिए धन्यवाद। हमने अपना खाता देखा, लेकिन ${x.ref ? `रेफरेंस ${x.ref} के साथ ` : ""}${x.amt} का कोई जमा नहीं मिला। कृपया अपने बैंक ऐप के लेन-देन इतिहास से UTR भेज दें, या भुगतान पूरा दिखने पर दोबारा भेजें।`,
    "Duplicate": (x) =>
      `${x.g} ${x.ref ? `रेफरेंस ${x.ref} वाला ` : ""}यही भुगतान किसी और के भुगतान के लिए भी भेजा गया है। कृपया अपने लेन-देन का विवरण भेजें ताकि हम आपका भुगतान पक्का कर सकें।`,
    "Can't verify yet": (x) =>
      `${x.g} भुगतान की जानकारी भेजने के लिए धन्यवाद, हमें मिल गई है। हमारा स्टेटमेंट अभी उस समय तक का नहीं है, इसलिए अगले अपडेट के बाद हम पक्का करेंगे। अभी आपको कुछ करने की ज़रूरत नहीं है।`,
  },
  te: {
    "Verified": (x) =>
      `${x.g} మీ ${x.amt} చెల్లింపు${x.ref ? ` (రిఫరెన్స్ ${x.ref})` : ""} మా ఖాతాలో కనిపించింది. ధన్యవాదాలు!`,
    "Likely match": (x) =>
      `${x.g} మీ చెల్లింపులా కనిపించే ఒక చెల్లింపు మాకు దొరికింది (${x.amt}${x.when ? `, ${x.when}` : ""}). దయచేసి మీ బ్యాంక్ యాప్‌లోని రిఫరెన్స్ నంబర్ పంపండి, అప్పుడు మేము నిర్ధారిస్తాము.`,
    "Contradicted": (x) =>
      x.stmt
        ? `${x.g} చెల్లింపు వివరాలు పంపినందుకు ధన్యవాదాలు. రిఫరెన్స్ ${x.ref} మా ఖాతాలో ₹${x.stmt} గా ఉంది, కానీ మీ స్క్రీన్‌షాట్‌లో ${x.amt} ఉంది. దయచేసి సరిచూసి సరైన స్క్రీన్‌షాట్ లేదా మిగిలిన మొత్తాన్ని పంపండి.`
        : `${x.g} చెల్లింపు వివరాలు పంపినందుకు ధన్యవాదాలు. రిఫరెన్స్ ${x.ref} కనిపించింది, కానీ కొన్ని వివరాలు (మొత్తం లేదా తేదీ వంటివి) మీ స్క్రీన్‌షాట్‌తో సరిపోలడం లేదు. దయచేసి మీ బ్యాంక్ యాప్‌లో మళ్లీ చూసి సరైన వివరాలు పంపండి.`,
    "Not found": (x) =>
      `${x.g} చెల్లింపు వివరాలు పంపినందుకు ధన్యవాదాలు. మేము మా ఖాతా చూశాము, కానీ ${x.ref ? `రిఫరెన్స్ ${x.ref} తో ` : ""}${x.amt} జమ కనిపించలేదు. దయచేసి మీ బ్యాంక్ యాప్ లావాదేవీ చరిత్ర నుండి UTR పంపండి, లేదా చెల్లింపు పూర్తయినట్లు కనిపించాక మళ్లీ పంపండి.`,
    "Duplicate": (x) =>
      `${x.g} ${x.ref ? `రిఫరెన్స్ ${x.ref} తో ఉన్న ` : ""}ఇదే చెల్లింపు మరొక చెల్లింపు కోసం కూడా పంపబడింది. దయచేసి మీ స్వంత లావాదేవీ వివరాలు పంపండి, అప్పుడు మేము మీ చెల్లింపును నిర్ధారిస్తాము.`,
    "Can't verify yet": (x) =>
      `${x.g} చెల్లింపు వివరాలు పంపినందుకు ధన్యవాదాలు, అవి మాకు అందాయి. మా స్టేట్‌మెంట్ ఇంకా ఆ సమయం వరకు లేదు, కాబట్టి తదుపరి అప్డేట్ తర్వాత నిర్ధారిస్తాము. ప్రస్తుతం మీరు ఏమీ చేయాల్సిన అవసరం లేదు.`,
  },
};

const inr = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: 2 });

function whenOf(ts?: string | null) {
  if (!ts) return "";
  const d = new Date(ts);
  return isNaN(d.getTime())
    ? ""
    : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

// "claim=800.0, statement=300.0" -> "300"
function statementAmount(v: Verdict): string {
  const raw = v.field_differences?.amount;
  const m = typeof raw === "string" ? raw.match(/statement=([\d.,]+)/) : null;
  const n = m ? Number(m[1].replace(/,/g, "")) : NaN;
  return isFinite(n) ? inr(n) : "";
}

export function buildReply(v: Verdict, c: Claim | undefined, lang: Lang): string {
  const a = c?.amount;
  const x: X = {
    g: GREET[lang]((c?.payer_name ?? "").trim().slice(0, 40)),
    amt: a != null && isFinite(Number(a)) ? `₹${inr(Number(a))}` : "₹—",
    stmt: statementAmount(v),
    ref: c?.reference ?? "",
    when: whenOf(c?.timestamp),
  };
  const fn = T[lang][v.status];
  return fn ? fn(x) : "";
}