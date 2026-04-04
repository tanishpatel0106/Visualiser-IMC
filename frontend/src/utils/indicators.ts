/**
 * Comprehensive Technical Indicator Computation Library
 *
 * All functions accept typed arrays and return arrays of the same length,
 * with `null` for positions where insufficient data exists.
 */

// ============================================================
// Helpers
// ============================================================

type N = number | null;

function sum(arr: number[], start: number, end: number): number {
  let s = 0;
  for (let i = start; i <= end; i++) s += arr[i];
  return s;
}

function mean(arr: number[], start: number, end: number): number {
  return sum(arr, start, end) / (end - start + 1);
}

function stddev(arr: number[], start: number, end: number): number {
  const m = mean(arr, start, end);
  let s = 0;
  for (let i = start; i <= end; i++) { const d = arr[i] - m; s += d * d; }
  return Math.sqrt(s / (end - start + 1));
}

function highest(arr: number[], start: number, end: number): number {
  let h = -Infinity;
  for (let i = start; i <= end; i++) if (arr[i] > h) h = arr[i];
  return h;
}

function lowest(arr: number[], start: number, end: number): number {
  let l = Infinity;
  for (let i = start; i <= end; i++) if (arr[i] < l) l = arr[i];
  return l;
}

function trueRange(high: number, low: number, prevClose: number): number {
  return Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose));
}

function wilderSmooth(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  if (values.length < period) return out;
  let s = 0;
  for (let i = 0; i < period; i++) s += values[i];
  out[period - 1] = s / period;
  for (let i = period; i < values.length; i++) {
    out[i] = ((out[i - 1] as number) * (period - 1) + values[i]) / period;
  }
  return out;
}

// ============================================================
// 1. Trend, Fair-Value, Price-Structure (Overlays)
// ============================================================

// --- Moving Averages ---

export function sma(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  let s = 0;
  for (let i = 0; i < values.length; i++) {
    s += values[i];
    if (i >= period) s -= values[i - period];
    if (i >= period - 1) out[i] = s / period;
  }
  return out;
}

export function ema(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  if (values.length === 0) return out;
  const k = 2 / (period + 1);
  out[0] = values[0];
  for (let i = 1; i < values.length; i++) {
    out[i] = values[i] * k + (out[i - 1] as number) * (1 - k);
  }
  // null out initial warm-up
  for (let i = 0; i < Math.min(period - 1, values.length); i++) out[i] = null;
  return out;
}

export function wma(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  const denom = (period * (period + 1)) / 2;
  for (let i = period - 1; i < values.length; i++) {
    let s = 0;
    for (let j = 0; j < period; j++) s += values[i - period + 1 + j] * (j + 1);
    out[i] = s / denom;
  }
  return out;
}

export function vwma(closes: number[], volumes: number[], period: number): N[] {
  const out: N[] = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    let pv = 0, v = 0;
    for (let j = i - period + 1; j <= i; j++) {
      pv += closes[j] * (volumes[j] || 0);
      v += volumes[j] || 0;
    }
    out[i] = v > 0 ? pv / v : closes[i];
  }
  return out;
}

export function hma(values: number[], period: number): N[] {
  const halfPeriod = Math.floor(period / 2);
  const sqrtPeriod = Math.max(1, Math.round(Math.sqrt(period)));
  const wmaHalf = wma(values, halfPeriod);
  const wmaFull = wma(values, period);

  const diff: number[] = [];
  for (let i = 0; i < values.length; i++) {
    if (wmaHalf[i] != null && wmaFull[i] != null) {
      diff.push(2 * (wmaHalf[i] as number) - (wmaFull[i] as number));
    } else {
      diff.push(values[i]);
    }
  }
  return wma(diff, sqrtPeriod);
}

export function dema(values: number[], period: number): N[] {
  const e1 = ema(values, period);
  const e1Nums = e1.map((v, i) => v ?? values[i]);
  const e2 = ema(e1Nums, period);
  return values.map((_, i) => {
    if (e1[i] == null || e2[i] == null) return null;
    return 2 * (e1[i] as number) - (e2[i] as number);
  });
}

export function tema(values: number[], period: number): N[] {
  const e1 = ema(values, period);
  const e1Nums = e1.map((v, i) => v ?? values[i]);
  const e2 = ema(e1Nums, period);
  const e2Nums = e2.map((v, i) => v ?? e1Nums[i]);
  const e3 = ema(e2Nums, period);
  return values.map((_, i) => {
    if (e1[i] == null || e2[i] == null || e3[i] == null) return null;
    return 3 * (e1[i] as number) - 3 * (e2[i] as number) + (e3[i] as number);
  });
}

export function kama(values: number[], period: number, fastPeriod = 2, slowPeriod = 30): N[] {
  const out: N[] = new Array(values.length).fill(null);
  if (values.length < period + 1) return out;
  const fastSC = 2 / (fastPeriod + 1);
  const slowSC = 2 / (slowPeriod + 1);

  out[period] = values[period];
  for (let i = period + 1; i < values.length; i++) {
    const direction = Math.abs(values[i] - values[i - period]);
    let volatility = 0;
    for (let j = i - period + 1; j <= i; j++) volatility += Math.abs(values[j] - values[j - 1]);
    const er = volatility !== 0 ? direction / volatility : 0;
    const sc = Math.pow(er * (fastSC - slowSC) + slowSC, 2);
    out[i] = (out[i - 1] as number) + sc * (values[i] - (out[i - 1] as number));
  }
  return out;
}

export function zlema(values: number[], period: number): N[] {
  const lag = Math.floor((period - 1) / 2);
  const adjusted = values.map((v, i) => i >= lag ? 2 * v - values[i - lag] : v);
  return ema(adjusted, period);
}

export function mcginleyDynamic(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  if (values.length === 0) return out;
  out[0] = values[0];
  for (let i = 1; i < values.length; i++) {
    const prev = (out[i - 1] ?? values[i - 1]) as number;
    const ratio = values[i] / prev;
    out[i] = prev + (values[i] - prev) / (period * Math.pow(ratio, 4));
  }
  for (let i = 0; i < Math.min(period - 1, values.length); i++) out[i] = null;
  return out;
}

export function alma(values: number[], period: number, offset = 0.85, sigma = 6): N[] {
  const out: N[] = new Array(values.length).fill(null);
  const m = offset * (period - 1);
  const s = period / sigma;
  const weights: number[] = [];
  let wSum = 0;
  for (let i = 0; i < period; i++) {
    const w = Math.exp(-((i - m) * (i - m)) / (2 * s * s));
    weights.push(w);
    wSum += w;
  }
  for (let i = 0; i < period; i++) weights[i] /= wSum;

  for (let i = period - 1; i < values.length; i++) {
    let v = 0;
    for (let j = 0; j < period; j++) v += values[i - period + 1 + j] * weights[j];
    out[i] = v;
  }
  return out;
}

// --- VWAP Variants ---

export function sessionVwap(prices: number[], volumes: number[]): number[] {
  const out: number[] = [];
  let pv = 0, vol = 0;
  for (let i = 0; i < prices.length; i++) {
    pv += prices[i] * (volumes[i] || 0);
    vol += volumes[i] || 0;
    out.push(vol > 0 ? pv / vol : prices[i]);
  }
  return out;
}

export function rollingVwap(prices: number[], volumes: number[], period: number): N[] {
  const out: N[] = new Array(prices.length).fill(null);
  for (let i = period - 1; i < prices.length; i++) {
    let pv = 0, v = 0;
    for (let j = i - period + 1; j <= i; j++) {
      pv += prices[j] * (volumes[j] || 0);
      v += volumes[j] || 0;
    }
    out[i] = v > 0 ? pv / v : prices[i];
  }
  return out;
}

export function twap(prices: number[], period: number): N[] {
  return sma(prices, period);
}

// --- Ichimoku ---

export function ichimokuTenkan(highs: number[], lows: number[], period = 9): N[] {
  const out: N[] = new Array(highs.length).fill(null);
  for (let i = period - 1; i < highs.length; i++) {
    out[i] = (highest(highs, i - period + 1, i) + lowest(lows, i - period + 1, i)) / 2;
  }
  return out;
}

export function ichimokuKijun(highs: number[], lows: number[], period = 26): N[] {
  return ichimokuTenkan(highs, lows, period);
}

export function ichimokuSenkouA(highs: number[], lows: number[], tenkanPeriod = 9, kijunPeriod = 26, displacement = 26): N[] {
  const tenkan = ichimokuTenkan(highs, lows, tenkanPeriod);
  const kijun = ichimokuTenkan(highs, lows, kijunPeriod);
  const out: N[] = new Array(highs.length + displacement).fill(null);
  for (let i = 0; i < highs.length; i++) {
    if (tenkan[i] != null && kijun[i] != null) {
      const idx = i + displacement;
      if (idx < out.length) out[idx] = ((tenkan[i] as number) + (kijun[i] as number)) / 2;
    }
  }
  return out.slice(0, highs.length);
}

export function ichimokuSenkouB(highs: number[], lows: number[], period = 52, displacement = 26): N[] {
  const base = ichimokuTenkan(highs, lows, period);
  const out: N[] = new Array(highs.length + displacement).fill(null);
  for (let i = 0; i < highs.length; i++) {
    if (base[i] != null) {
      const idx = i + displacement;
      if (idx < out.length) out[idx] = base[i];
    }
  }
  return out.slice(0, highs.length);
}

// --- Moving Average Envelope ---

export function maEnvelope(values: number[], period: number, pct = 0.025): { upper: N[]; mid: N[]; lower: N[] } {
  const mid = sma(values, period);
  const upper: N[] = mid.map(v => v != null ? v * (1 + pct) : null);
  const lower: N[] = mid.map(v => v != null ? v * (1 - pct) : null);
  return { upper, mid, lower };
}

// --- Regression ---

export function linearRegression(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
    for (let j = 0; j < period; j++) {
      sumX += j;
      sumY += values[i - period + 1 + j];
      sumXY += j * values[i - period + 1 + j];
      sumX2 += j * j;
    }
    const slope = (period * sumXY - sumX * sumY) / (period * sumX2 - sumX * sumX);
    const intercept = (sumY - slope * sumX) / period;
    out[i] = intercept + slope * (period - 1);
  }
  return out;
}

export function linearRegressionChannel(values: number[], period: number, mult = 2): { mid: N[]; upper: N[]; lower: N[] } {
  const mid = linearRegression(values, period);
  const upper: N[] = new Array(values.length).fill(null);
  const lower: N[] = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    if (mid[i] == null) continue;
    const s = stddev(values, i - period + 1, i);
    upper[i] = (mid[i] as number) + mult * s;
    lower[i] = (mid[i] as number) - mult * s;
  }
  return { mid, upper, lower };
}

export function stdDevChannel(values: number[], period: number, mult = 2): { mid: N[]; upper: N[]; lower: N[] } {
  const mid = sma(values, period);
  const upper: N[] = new Array(values.length).fill(null);
  const lower: N[] = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    if (mid[i] == null) continue;
    const s = stddev(values, i - period + 1, i);
    upper[i] = (mid[i] as number) + mult * s;
    lower[i] = (mid[i] as number) - mult * s;
  }
  return { mid, upper, lower };
}

// ============================================================
// 2. Bands, Channels, Support/Resistance (Overlays)
// ============================================================

export function bollingerBands(values: number[], period: number, k = 2): { mid: N[]; upper: N[]; lower: N[] } {
  const mid = sma(values, period);
  const upper: N[] = new Array(values.length).fill(null);
  const lower: N[] = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    if (mid[i] == null) continue;
    const s = stddev(values, i - period + 1, i);
    upper[i] = (mid[i] as number) + k * s;
    lower[i] = (mid[i] as number) - k * s;
  }
  return { mid, upper, lower };
}

export function keltnerChannel(closes: number[], highs: number[], lows: number[], emaPeriod = 20, atrPeriod = 10, mult = 1.5): { mid: N[]; upper: N[]; lower: N[] } {
  const mid = ema(closes, emaPeriod);
  const atrVals = atr(highs, lows, closes, atrPeriod);
  const upper: N[] = new Array(closes.length).fill(null);
  const lower: N[] = new Array(closes.length).fill(null);
  for (let i = 0; i < closes.length; i++) {
    if (mid[i] != null && atrVals[i] != null) {
      upper[i] = (mid[i] as number) + mult * (atrVals[i] as number);
      lower[i] = (mid[i] as number) - mult * (atrVals[i] as number);
    }
  }
  return { mid, upper, lower };
}

export function donchianChannel(highs: number[], lows: number[], period: number): { upper: N[]; mid: N[]; lower: N[] } {
  const upper: N[] = new Array(highs.length).fill(null);
  const lower: N[] = new Array(highs.length).fill(null);
  const mid: N[] = new Array(highs.length).fill(null);
  for (let i = period - 1; i < highs.length; i++) {
    const h = highest(highs, i - period + 1, i);
    const l = lowest(lows, i - period + 1, i);
    upper[i] = h;
    lower[i] = l;
    mid[i] = (h + l) / 2;
  }
  return { upper, mid, lower };
}

export function atrBands(closes: number[], highs: number[], lows: number[], period = 14, mult = 2): { upper: N[]; mid: N[]; lower: N[] } {
  const mid = ema(closes, period);
  const atrVals = atr(highs, lows, closes, period);
  const upper: N[] = new Array(closes.length).fill(null);
  const lower: N[] = new Array(closes.length).fill(null);
  for (let i = 0; i < closes.length; i++) {
    if (mid[i] != null && atrVals[i] != null) {
      upper[i] = (mid[i] as number) + mult * (atrVals[i] as number);
      lower[i] = (mid[i] as number) - mult * (atrVals[i] as number);
    }
  }
  return { upper, mid, lower };
}

export function supertrend(closes: number[], highs: number[], lows: number[], period = 10, mult = 3): { line: N[]; direction: N[] } {
  const atrVals = atr(highs, lows, closes, period);
  const line: N[] = new Array(closes.length).fill(null);
  const direction: N[] = new Array(closes.length).fill(null);
  let upperBand = 0, lowerBand = 0, prevUpper = 0, prevLower = 0, dir = 1;

  for (let i = 0; i < closes.length; i++) {
    if (atrVals[i] == null) continue;
    const basicUpper = (highs[i] + lows[i]) / 2 + mult * (atrVals[i] as number);
    const basicLower = (highs[i] + lows[i]) / 2 - mult * (atrVals[i] as number);
    upperBand = basicUpper < prevUpper || closes[i - 1] > prevUpper ? basicUpper : prevUpper;
    lowerBand = basicLower > prevLower || closes[i - 1] < prevLower ? basicLower : prevLower;

    if (dir === 1 && closes[i] < lowerBand) dir = -1;
    else if (dir === -1 && closes[i] > upperBand) dir = 1;

    line[i] = dir === 1 ? lowerBand : upperBand;
    direction[i] = dir;
    prevUpper = upperBand;
    prevLower = lowerBand;
  }
  return { line, direction };
}

export function parabolicSar(highs: number[], lows: number[], accelInit = 0.02, accelMax = 0.2): N[] {
  const out: N[] = new Array(highs.length).fill(null);
  if (highs.length < 2) return out;
  let isLong = true, af = accelInit, ep = highs[0], sar = lows[0];

  for (let i = 1; i < highs.length; i++) {
    const prevSar = sar;
    sar = prevSar + af * (ep - prevSar);
    if (isLong) {
      sar = Math.min(sar, lows[i - 1], i >= 2 ? lows[i - 2] : lows[i - 1]);
      if (lows[i] < sar) {
        isLong = false; sar = ep; ep = lows[i]; af = accelInit;
      } else {
        if (highs[i] > ep) { ep = highs[i]; af = Math.min(af + accelInit, accelMax); }
      }
    } else {
      sar = Math.max(sar, highs[i - 1], i >= 2 ? highs[i - 2] : highs[i - 1]);
      if (highs[i] > sar) {
        isLong = true; sar = ep; ep = highs[i]; af = accelInit;
      } else {
        if (lows[i] < ep) { ep = lows[i]; af = Math.min(af + accelInit, accelMax); }
      }
    }
    out[i] = sar;
  }
  return out;
}

export function chandelierExit(highs: number[], lows: number[], closes: number[], period = 22, mult = 3): { longExit: N[]; shortExit: N[] } {
  const atrVals = atr(highs, lows, closes, period);
  const longExit: N[] = new Array(highs.length).fill(null);
  const shortExit: N[] = new Array(highs.length).fill(null);
  for (let i = period - 1; i < highs.length; i++) {
    if (atrVals[i] == null) continue;
    longExit[i] = highest(highs, i - period + 1, i) - mult * (atrVals[i] as number);
    shortExit[i] = lowest(lows, i - period + 1, i) + mult * (atrVals[i] as number);
  }
  return { longExit, shortExit };
}

// --- Pivot Points ---

export function pivotPoints(highs: number[], lows: number[], closes: number[]): { pp: N[]; r1: N[]; r2: N[]; r3: N[]; s1: N[]; s2: N[]; s3: N[] } {
  const len = highs.length;
  const pp: N[] = new Array(len).fill(null);
  const r1: N[] = new Array(len).fill(null);
  const r2: N[] = new Array(len).fill(null);
  const r3: N[] = new Array(len).fill(null);
  const s1: N[] = new Array(len).fill(null);
  const s2: N[] = new Array(len).fill(null);
  const s3: N[] = new Array(len).fill(null);
  for (let i = 1; i < len; i++) {
    const p = (highs[i - 1] + lows[i - 1] + closes[i - 1]) / 3;
    pp[i] = p; r1[i] = 2 * p - lows[i - 1]; s1[i] = 2 * p - highs[i - 1];
    r2[i] = p + (highs[i - 1] - lows[i - 1]); s2[i] = p - (highs[i - 1] - lows[i - 1]);
    r3[i] = highs[i - 1] + 2 * (p - lows[i - 1]); s3[i] = lows[i - 1] - 2 * (highs[i - 1] - p);
  }
  return { pp, r1, r2, r3, s1, s2, s3 };
}

export function camarillaPivots(highs: number[], lows: number[], closes: number[]): { pp: N[]; r1: N[]; r2: N[]; r3: N[]; r4: N[]; s1: N[]; s2: N[]; s3: N[]; s4: N[] } {
  const len = highs.length;
  const pp: N[] = new Array(len).fill(null);
  const r1: N[] = new Array(len).fill(null); const r2: N[] = new Array(len).fill(null);
  const r3: N[] = new Array(len).fill(null); const r4: N[] = new Array(len).fill(null);
  const s1: N[] = new Array(len).fill(null); const s2: N[] = new Array(len).fill(null);
  const s3: N[] = new Array(len).fill(null); const s4: N[] = new Array(len).fill(null);
  for (let i = 1; i < len; i++) {
    const h = highs[i - 1], l = lows[i - 1], c = closes[i - 1];
    const r = h - l;
    pp[i] = (h + l + c) / 3;
    r1[i] = c + r * 1.1 / 12; r2[i] = c + r * 1.1 / 6; r3[i] = c + r * 1.1 / 4; r4[i] = c + r * 1.1 / 2;
    s1[i] = c - r * 1.1 / 12; s2[i] = c - r * 1.1 / 6; s3[i] = c - r * 1.1 / 4; s4[i] = c - r * 1.1 / 2;
  }
  return { pp, r1, r2, r3, r4, s1, s2, s3, s4 };
}

export function woodiePivots(highs: number[], lows: number[], opens: number[], closes: number[]): { pp: N[]; r1: N[]; r2: N[]; s1: N[]; s2: N[] } {
  const len = highs.length;
  const pp: N[] = new Array(len).fill(null);
  const r1: N[] = new Array(len).fill(null); const r2: N[] = new Array(len).fill(null);
  const s1: N[] = new Array(len).fill(null); const s2: N[] = new Array(len).fill(null);
  for (let i = 1; i < len; i++) {
    const p = (highs[i - 1] + lows[i - 1] + 2 * opens[i]) / 4;
    pp[i] = p;
    r1[i] = 2 * p - lows[i - 1]; s1[i] = 2 * p - highs[i - 1];
    r2[i] = p + highs[i - 1] - lows[i - 1]; s2[i] = p - highs[i - 1] + lows[i - 1];
  }
  return { pp, r1, r2, s1, s2 };
}

// --- Session / Range Levels ---

export function sessionHighLow(highs: number[], lows: number[]): { high: number[]; low: number[] } {
  const h: number[] = [];
  const l: number[] = [];
  let runHigh = -Infinity, runLow = Infinity;
  for (let i = 0; i < highs.length; i++) {
    if (highs[i] > runHigh) runHigh = highs[i];
    if (lows[i] < runLow) runLow = lows[i];
    h.push(runHigh);
    l.push(runLow);
  }
  return { high: h, low: l };
}

export function rollingHighLow(highs: number[], lows: number[], period: number): { high: N[]; low: N[] } {
  const h: N[] = new Array(highs.length).fill(null);
  const l: N[] = new Array(highs.length).fill(null);
  for (let i = period - 1; i < highs.length; i++) {
    h[i] = highest(highs, i - period + 1, i);
    l[i] = lowest(lows, i - period + 1, i);
  }
  return { high: h, low: l };
}

export function previousBarHighLow(highs: number[], lows: number[]): { high: N[]; low: N[] } {
  const h: N[] = new Array(highs.length).fill(null);
  const l: N[] = new Array(lows.length).fill(null);
  for (let i = 1; i < highs.length; i++) {
    h[i] = highs[i - 1];
    l[i] = lows[i - 1];
  }
  return { high: h, low: l };
}

export function previousSessionClose(closes: number[]): N[] {
  const out: N[] = new Array(closes.length).fill(null);
  for (let i = 1; i < closes.length; i++) out[i] = closes[i - 1];
  return out;
}

// ============================================================
// 3. Momentum and Oscillator Studies (Separate Panes)
// ============================================================

export function rsi(values: number[], period = 14): N[] {
  const out: N[] = new Array(values.length).fill(null);
  if (values.length < period + 1) return out;
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = values[i] - values[i - 1];
    if (d > 0) avgGain += d; else avgLoss -= d;
  }
  avgGain /= period;
  avgLoss /= period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    avgGain = (avgGain * (period - 1) + (d > 0 ? d : 0)) / period;
    avgLoss = (avgLoss * (period - 1) + (d < 0 ? -d : 0)) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

export function stochastic(highs: number[], lows: number[], closes: number[], kPeriod = 14, dPeriod = 3): { k: N[]; d: N[] } {
  const k: N[] = new Array(closes.length).fill(null);
  for (let i = kPeriod - 1; i < closes.length; i++) {
    const hh = highest(highs, i - kPeriod + 1, i);
    const ll = lowest(lows, i - kPeriod + 1, i);
    k[i] = hh !== ll ? ((closes[i] - ll) / (hh - ll)) * 100 : 50;
  }
  const kNums = k.map((v, i) => v ?? closes[i]);
  const d = sma(kNums, dPeriod);
  for (let i = 0; i < kPeriod - 1; i++) d[i] = null;
  return { k, d };
}

export function stochasticRsi(values: number[], rsiPeriod = 14, stochPeriod = 14, kSmooth = 3, dSmooth = 3): { k: N[]; d: N[] } {
  const rsiVals = rsi(values, rsiPeriod);
  const rsiNums: number[] = rsiVals.map(v => v ?? 50);
  const k: N[] = new Array(values.length).fill(null);
  for (let i = rsiPeriod + stochPeriod - 1; i < values.length; i++) {
    const hh = highest(rsiNums, i - stochPeriod + 1, i);
    const ll = lowest(rsiNums, i - stochPeriod + 1, i);
    k[i] = hh !== ll ? ((rsiNums[i] - ll) / (hh - ll)) * 100 : 50;
  }
  const kNums = k.map(v => v ?? 50);
  const kSmoothed = sma(kNums, kSmooth);
  const dSmoothed = sma(kNums, dSmooth);
  return { k: kSmoothed, d: dSmoothed };
}

export function macd(values: number[], fast = 12, slow = 26, signal = 9): { macd: N[]; signal: N[]; histogram: N[] } {
  const emaFast = ema(values, fast);
  const emaSlow = ema(values, slow);
  const macdLine: N[] = values.map((_, i) => {
    if (emaFast[i] != null && emaSlow[i] != null) return (emaFast[i] as number) - (emaSlow[i] as number);
    return null;
  });
  const macdNums = macdLine.map(v => v ?? 0);
  const signalLine = ema(macdNums, signal);
  const histogram: N[] = values.map((_, i) => {
    if (macdLine[i] != null && signalLine[i] != null) return (macdLine[i] as number) - (signalLine[i] as number);
    return null;
  });
  for (let i = 0; i < slow - 1; i++) { macdLine[i] = null; signalLine[i] = null; histogram[i] = null; }
  return { macd: macdLine, signal: signalLine, histogram };
}

export function ppo(values: number[], fast = 12, slow = 26, signal = 9): { ppo: N[]; signal: N[]; histogram: N[] } {
  const emaFast = ema(values, fast);
  const emaSlow = ema(values, slow);
  const ppoLine: N[] = values.map((_, i) => {
    if (emaFast[i] != null && emaSlow[i] != null && (emaSlow[i] as number) !== 0)
      return ((emaFast[i] as number) - (emaSlow[i] as number)) / (emaSlow[i] as number) * 100;
    return null;
  });
  const ppoNums = ppoLine.map(v => v ?? 0);
  const signalLine = ema(ppoNums, signal);
  const hist: N[] = values.map((_, i) => {
    if (ppoLine[i] != null && signalLine[i] != null) return (ppoLine[i] as number) - (signalLine[i] as number);
    return null;
  });
  return { ppo: ppoLine, signal: signalLine, histogram: hist };
}

export function roc(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  for (let i = period; i < values.length; i++) {
    if (values[i - period] !== 0) out[i] = ((values[i] - values[i - period]) / values[i - period]) * 100;
  }
  return out;
}

export function momentum(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  for (let i = period; i < values.length; i++) {
    out[i] = values[i] - values[i - period];
  }
  return out;
}

export function cci(highs: number[], lows: number[], closes: number[], period = 20): N[] {
  const tp = closes.map((c, i) => (highs[i] + lows[i] + c) / 3);
  const out: N[] = new Array(closes.length).fill(null);
  for (let i = period - 1; i < tp.length; i++) {
    const m = mean(tp, i - period + 1, i);
    let md = 0;
    for (let j = i - period + 1; j <= i; j++) md += Math.abs(tp[j] - m);
    md /= period;
    out[i] = md !== 0 ? (tp[i] - m) / (0.015 * md) : 0;
  }
  return out;
}

export function williamsR(highs: number[], lows: number[], closes: number[], period = 14): N[] {
  const out: N[] = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    const hh = highest(highs, i - period + 1, i);
    const ll = lowest(lows, i - period + 1, i);
    out[i] = hh !== ll ? ((hh - closes[i]) / (hh - ll)) * -100 : 0;
  }
  return out;
}

export function ultimateOscillator(highs: number[], lows: number[], closes: number[], p1 = 7, p2 = 14, p3 = 28): N[] {
  const out: N[] = new Array(closes.length).fill(null);
  const bp: number[] = [0];
  const tr: number[] = [highs[0] - lows[0]];
  for (let i = 1; i < closes.length; i++) {
    bp.push(closes[i] - Math.min(lows[i], closes[i - 1]));
    tr.push(trueRange(highs[i], lows[i], closes[i - 1]));
  }
  for (let i = p3 - 1; i < closes.length; i++) {
    const avg1 = sum(bp, i - p1 + 1, i) / sum(tr, i - p1 + 1, i);
    const avg2 = sum(bp, i - p2 + 1, i) / sum(tr, i - p2 + 1, i);
    const avg3 = sum(bp, i - p3 + 1, i) / sum(tr, i - p3 + 1, i);
    out[i] = 100 * (4 * avg1 + 2 * avg2 + avg3) / 7;
  }
  return out;
}

export function awesomeOscillator(highs: number[], lows: number[], fast = 5, slow = 34): N[] {
  const mp = highs.map((h, i) => (h + lows[i]) / 2);
  const smaFast = sma(mp, fast);
  const smaSlow = sma(mp, slow);
  return mp.map((_, i) => {
    if (smaFast[i] != null && smaSlow[i] != null) return (smaFast[i] as number) - (smaSlow[i] as number);
    return null;
  });
}

export function acceleratorOscillator(highs: number[], lows: number[], fast = 5, slow = 34, smoothPeriod = 5): N[] {
  const ao = awesomeOscillator(highs, lows, fast, slow);
  const aoNums = ao.map(v => v ?? 0);
  const aoSma = sma(aoNums, smoothPeriod);
  return ao.map((v, i) => {
    if (v != null && aoSma[i] != null) return v - (aoSma[i] as number);
    return null;
  });
}

export function trix(values: number[], period: number): N[] {
  const e1 = ema(values, period);
  const e1Nums = e1.map((v, i) => v ?? values[i]);
  const e2 = ema(e1Nums, period);
  const e2Nums = e2.map((v, i) => v ?? e1Nums[i]);
  const e3 = ema(e2Nums, period);
  const out: N[] = new Array(values.length).fill(null);
  for (let i = 1; i < values.length; i++) {
    if (e3[i] != null && e3[i - 1] != null && (e3[i - 1] as number) !== 0) {
      out[i] = ((e3[i] as number) - (e3[i - 1] as number)) / (e3[i - 1] as number) * 100;
    }
  }
  return out;
}

export function tsi(values: number[], longPeriod = 25, shortPeriod = 13): N[] {
  const pc: number[] = [0];
  for (let i = 1; i < values.length; i++) pc.push(values[i] - values[i - 1]);
  const pcAbs = pc.map(Math.abs);
  const ds = ema(pc, longPeriod);
  const dsNums = ds.map(v => v ?? 0);
  const dss = ema(dsNums, shortPeriod);
  const absDs = ema(pcAbs, longPeriod);
  const absDsNums = absDs.map(v => v ?? 0);
  const absDss = ema(absDsNums, shortPeriod);
  return values.map((_, i) => {
    if (dss[i] != null && absDss[i] != null && (absDss[i] as number) !== 0)
      return ((dss[i] as number) / (absDss[i] as number)) * 100;
    return null;
  });
}

export function cmo(values: number[], period = 14): N[] {
  const out: N[] = new Array(values.length).fill(null);
  for (let i = period; i < values.length; i++) {
    let gains = 0, losses = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const d = values[j] - values[j - 1];
      if (d > 0) gains += d; else losses -= d;
    }
    const s = gains + losses;
    out[i] = s !== 0 ? ((gains - losses) / s) * 100 : 0;
  }
  return out;
}

export function dpo(values: number[], period: number): N[] {
  const offset = Math.floor(period / 2) + 1;
  const smaVals = sma(values, period);
  const out: N[] = new Array(values.length).fill(null);
  for (let i = offset; i < values.length; i++) {
    if (smaVals[i] != null) out[i - offset] = values[i - offset] - (smaVals[i] as number);
  }
  return out;
}

export function connorsRsi(values: number[], rsiPeriod = 3, streakPeriod = 2, rankPeriod = 100): N[] {
  const rsiVals = rsi(values, rsiPeriod);
  // Streak RSI
  const streak: number[] = [0];
  for (let i = 1; i < values.length; i++) {
    if (values[i] > values[i - 1]) streak.push(streak[i - 1] > 0 ? streak[i - 1] + 1 : 1);
    else if (values[i] < values[i - 1]) streak.push(streak[i - 1] < 0 ? streak[i - 1] - 1 : -1);
    else streak.push(0);
  }
  const streakRsi = rsi(streak.map(v => v + 100), streakPeriod);
  // Percent rank
  const pctRank: N[] = new Array(values.length).fill(null);
  for (let i = rankPeriod; i < values.length; i++) {
    const change = values[i] - values[i - 1];
    let count = 0;
    for (let j = i - rankPeriod; j < i; j++) {
      if ((values[j + 1] - values[j]) < change) count++;
    }
    pctRank[i] = (count / rankPeriod) * 100;
  }
  return values.map((_, i) => {
    if (rsiVals[i] != null && streakRsi[i] != null && pctRank[i] != null)
      return ((rsiVals[i] as number) + (streakRsi[i] as number) + (pctRank[i] as number)) / 3;
    return null;
  });
}

export function fisherTransform(highs: number[], lows: number[], period = 10): { fisher: N[]; trigger: N[] } {
  const out: N[] = new Array(highs.length).fill(null);
  const trigger: N[] = new Array(highs.length).fill(null);
  let val = 0, prev = 0;
  for (let i = period - 1; i < highs.length; i++) {
    const hh = highest(highs, i - period + 1, i);
    const ll = lowest(lows, i - period + 1, i);
    const raw = hh !== ll ? ((highs[i] + lows[i]) / 2 - ll) / (hh - ll) - 0.5 : 0;
    val = 0.66 * raw + 0.67 * val;
    val = Math.max(-0.999, Math.min(0.999, val));
    const fisher = 0.5 * Math.log((1 + val) / (1 - val)) + 0.5 * prev;
    trigger[i] = prev;
    out[i] = fisher;
    prev = fisher;
  }
  return { fisher: out, trigger };
}

export function schaffTrendCycle(values: number[], fast = 23, slow = 50, cyclePeriod = 10): N[] {
  const macdVals = macd(values, fast, slow, 1);
  const macdNums = macdVals.macd.map(v => v ?? 0);
  // First stochastic
  const pf: number[] = new Array(values.length).fill(0);
  for (let i = cyclePeriod - 1; i < values.length; i++) {
    const hh = highest(macdNums, i - cyclePeriod + 1, i);
    const ll = lowest(macdNums, i - cyclePeriod + 1, i);
    const raw = hh !== ll ? ((macdNums[i] - ll) / (hh - ll)) * 100 : 50;
    pf[i] = i > 0 ? pf[i - 1] + 0.5 * (raw - pf[i - 1]) : raw;
  }
  // Second stochastic
  const out: N[] = new Array(values.length).fill(null);
  let pfSmooth = 0;
  for (let i = cyclePeriod * 2; i < values.length; i++) {
    const hh = highest(pf, i - cyclePeriod + 1, i);
    const ll = lowest(pf, i - cyclePeriod + 1, i);
    const raw = hh !== ll ? ((pf[i] - ll) / (hh - ll)) * 100 : 50;
    pfSmooth = pfSmooth + 0.5 * (raw - pfSmooth);
    out[i] = pfSmooth;
  }
  return out;
}

export function relativeVigorIndex(opens: number[], highs: number[], lows: number[], closes: number[], period = 10): { rvi: N[]; signal: N[] } {
  const num: number[] = new Array(closes.length).fill(0);
  const den: number[] = new Array(closes.length).fill(0);
  for (let i = 3; i < closes.length; i++) {
    num[i] = ((closes[i] - opens[i]) + 2 * (closes[i - 1] - opens[i - 1]) + 2 * (closes[i - 2] - opens[i - 2]) + (closes[i - 3] - opens[i - 3])) / 6;
    den[i] = ((highs[i] - lows[i]) + 2 * (highs[i - 1] - lows[i - 1]) + 2 * (highs[i - 2] - lows[i - 2]) + (highs[i - 3] - lows[i - 3])) / 6;
  }
  const rviVals: N[] = new Array(closes.length).fill(null);
  for (let i = period + 2; i < closes.length; i++) {
    const numSum = sum(num, i - period + 1, i);
    const denSum = sum(den, i - period + 1, i);
    rviVals[i] = denSum !== 0 ? numSum / denSum : 0;
  }
  const signal: N[] = new Array(closes.length).fill(null);
  for (let i = period + 5; i < closes.length; i++) {
    if (rviVals[i] != null && rviVals[i - 1] != null && rviVals[i - 2] != null && rviVals[i - 3] != null)
      signal[i] = ((rviVals[i] as number) + 2 * (rviVals[i - 1] as number) + 2 * (rviVals[i - 2] as number) + (rviVals[i - 3] as number)) / 6;
  }
  return { rvi: rviVals, signal };
}

export function elderRayBull(highs: number[], closes: number[], period = 13): N[] {
  const emaVals = ema(closes, period);
  return highs.map((h, i) => emaVals[i] != null ? h - (emaVals[i] as number) : null);
}

export function elderRayBear(lows: number[], closes: number[], period = 13): N[] {
  const emaVals = ema(closes, period);
  return lows.map((l, i) => emaVals[i] != null ? l - (emaVals[i] as number) : null);
}

export function aroon(highs: number[], lows: number[], period = 25): { up: N[]; down: N[]; oscillator: N[] } {
  const up: N[] = new Array(highs.length).fill(null);
  const down: N[] = new Array(highs.length).fill(null);
  const osc: N[] = new Array(highs.length).fill(null);
  for (let i = period; i < highs.length; i++) {
    let hIdx = 0, lIdx = 0;
    for (let j = 1; j <= period; j++) {
      if (highs[i - j] > highs[i - hIdx]) hIdx = j;
      if (lows[i - j] < lows[i - lIdx]) lIdx = j;
    }
    up[i] = ((period - hIdx) / period) * 100;
    down[i] = ((period - lIdx) / period) * 100;
    osc[i] = (up[i] as number) - (down[i] as number);
  }
  return { up, down, oscillator: osc };
}

export function adx(highs: number[], lows: number[], closes: number[], period = 14): { adx: N[]; plusDi: N[]; minusDi: N[] } {
  const len = highs.length;
  const plusDm: number[] = [0];
  const minusDm: number[] = [0];
  const trVals: number[] = [highs[0] - lows[0]];
  for (let i = 1; i < len; i++) {
    const upMove = highs[i] - highs[i - 1];
    const downMove = lows[i - 1] - lows[i];
    plusDm.push(upMove > downMove && upMove > 0 ? upMove : 0);
    minusDm.push(downMove > upMove && downMove > 0 ? downMove : 0);
    trVals.push(trueRange(highs[i], lows[i], closes[i - 1]));
  }
  const smoothTr = wilderSmooth(trVals, period);
  const smoothPlusDm = wilderSmooth(plusDm, period);
  const smoothMinusDm = wilderSmooth(minusDm, period);
  const plusDi: N[] = new Array(len).fill(null);
  const minusDi: N[] = new Array(len).fill(null);
  const dx: number[] = new Array(len).fill(0);
  for (let i = 0; i < len; i++) {
    if (smoothTr[i] != null && (smoothTr[i] as number) !== 0) {
      plusDi[i] = ((smoothPlusDm[i] as number) / (smoothTr[i] as number)) * 100;
      minusDi[i] = ((smoothMinusDm[i] as number) / (smoothTr[i] as number)) * 100;
      const s = (plusDi[i] as number) + (minusDi[i] as number);
      dx[i] = s !== 0 ? (Math.abs((plusDi[i] as number) - (minusDi[i] as number)) / s) * 100 : 0;
    }
  }
  const adxVals = wilderSmooth(dx, period);
  return { adx: adxVals, plusDi, minusDi };
}

export function vortex(highs: number[], lows: number[], closes: number[], period = 14): { plus: N[]; minus: N[] } {
  const plus: N[] = new Array(highs.length).fill(null);
  const minus: N[] = new Array(highs.length).fill(null);
  for (let i = period; i < highs.length; i++) {
    let vmPlus = 0, vmMinus = 0, trSum = 0;
    for (let j = i - period + 1; j <= i; j++) {
      vmPlus += Math.abs(highs[j] - lows[j - 1]);
      vmMinus += Math.abs(lows[j] - highs[j - 1]);
      trSum += trueRange(highs[j], lows[j], closes[j - 1]);
    }
    plus[i] = trSum !== 0 ? vmPlus / trSum : 0;
    minus[i] = trSum !== 0 ? vmMinus / trSum : 0;
  }
  return { plus, minus };
}

export function massIndex(highs: number[], lows: number[], emaPeriod = 9, sumPeriod = 25): N[] {
  const spread = highs.map((h, i) => h - lows[i]);
  const e1 = ema(spread, emaPeriod);
  const e1Nums = e1.map((v, i) => v ?? spread[i]);
  const e2 = ema(e1Nums, emaPeriod);
  const ratio: number[] = spread.map((_, i) => {
    if (e1[i] != null && e2[i] != null && (e2[i] as number) !== 0) return (e1[i] as number) / (e2[i] as number);
    return 1;
  });
  const out: N[] = new Array(highs.length).fill(null);
  for (let i = sumPeriod - 1; i < ratio.length; i++) {
    out[i] = sum(ratio, i - sumPeriod + 1, i);
  }
  return out;
}

export function coppockCurve(values: number[], longRoc = 14, shortRoc = 11, wmaPeriod = 10): N[] {
  const longR = roc(values, longRoc);
  const shortR = roc(values, shortRoc);
  const combined = values.map((_, i) => {
    if (longR[i] != null && shortR[i] != null) return (longR[i] as number) + (shortR[i] as number);
    return 0;
  });
  return wma(combined, wmaPeriod);
}

export function kst(values: number[], r1 = 10, r2 = 15, r3 = 20, r4 = 30, s1 = 10, s2 = 10, s3 = 10, s4 = 15, sigPeriod = 9): { kst: N[]; signal: N[] } {
  const roc1 = roc(values, r1).map(v => v ?? 0);
  const roc2 = roc(values, r2).map(v => v ?? 0);
  const roc3 = roc(values, r3).map(v => v ?? 0);
  const roc4 = roc(values, r4).map(v => v ?? 0);
  const sma1 = sma(roc1, s1).map(v => v ?? 0);
  const sma2 = sma(roc2, s2).map(v => v ?? 0);
  const sma3 = sma(roc3, s3).map(v => v ?? 0);
  const sma4 = sma(roc4, s4).map(v => v ?? 0);
  const kstVals: number[] = values.map((_, i) => sma1[i] + 2 * sma2[i] + 3 * sma3[i] + 4 * sma4[i]);
  const signal = sma(kstVals, sigPeriod);
  const kstOut: N[] = kstVals.map((v, i) => i >= r4 + s4 - 2 ? v : null);
  return { kst: kstOut, signal };
}

export function qstick(opens: number[], closes: number[], period: number): N[] {
  const diff = closes.map((c, i) => c - opens[i]);
  return sma(diff, period);
}

export function squeezeMomentum(closes: number[], highs: number[], lows: number[], bbPeriod = 20, bbMult = 2, kcPeriod = 20, kcMult = 1.5): { value: N[]; squeeze: boolean[] } {
  const bb = bollingerBands(closes, bbPeriod, bbMult);
  const kc = keltnerChannel(closes, highs, lows, kcPeriod, kcPeriod, kcMult);
  const squeeze: boolean[] = closes.map((_, i) =>
    bb.lower[i] != null && bb.upper[i] != null && kc.lower[i] != null && kc.upper[i] != null &&
    (bb.lower[i] as number) > (kc.lower[i] as number) && (bb.upper[i] as number) < (kc.upper[i] as number)
  );
  // Momentum = linear regression of (close - midline of Donchian+SMA average)
  const dc = donchianChannel(highs, lows, kcPeriod);
  const midDc = dc.mid;
  const midSma = sma(closes, kcPeriod);
  const delta = closes.map((c, i) => {
    const m = midDc[i] != null && midSma[i] != null ? ((midDc[i] as number) + (midSma[i] as number)) / 2 : c;
    return c - m;
  });
  const value = linearRegression(delta, kcPeriod);
  return { value, squeeze };
}

export function choppinessIndex(highs: number[], lows: number[], closes: number[], period = 14): N[] {
  const out: N[] = new Array(closes.length).fill(null);
  for (let i = period; i < closes.length; i++) {
    let atrSum = 0;
    for (let j = i - period + 1; j <= i; j++) {
      atrSum += trueRange(highs[j], lows[j], closes[j - 1]);
    }
    const hh = highest(highs, i - period + 1, i);
    const ll = lowest(lows, i - period + 1, i);
    const range = hh - ll;
    out[i] = range > 0 ? 100 * Math.log10(atrSum / range) / Math.log10(period) : 50;
  }
  return out;
}

export function efficiencyRatio(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  for (let i = period; i < values.length; i++) {
    const direction = Math.abs(values[i] - values[i - period]);
    let volatility = 0;
    for (let j = i - period + 1; j <= i; j++) volatility += Math.abs(values[j] - values[j - 1]);
    out[i] = volatility !== 0 ? direction / volatility : 0;
  }
  return out;
}

export function hurstExponent(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    const slice = values.slice(i - period + 1, i + 1);
    const m = slice.reduce((a, b) => a + b, 0) / period;
    const cumDev: number[] = [];
    let cumSum = 0;
    for (let j = 0; j < period; j++) { cumSum += slice[j] - m; cumDev.push(cumSum); }
    const R = Math.max(...cumDev) - Math.min(...cumDev);
    const S = Math.sqrt(slice.reduce((s, v) => s + (v - m) ** 2, 0) / period);
    if (S > 0 && R > 0) {
      out[i] = Math.log(R / S) / Math.log(period);
    }
  }
  return out;
}

export function fractalDimension(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  const halfP = Math.floor(period / 2);
  for (let i = period - 1; i < values.length; i++) {
    const n3 = (highest(values as number[], i - period + 1, i) - lowest(values as number[], i - period + 1, i)) / period;
    const n1 = (highest(values as number[], i - period + 1, i - halfP) - lowest(values as number[], i - period + 1, i - halfP)) / halfP;
    const n2 = (highest(values as number[], i - halfP + 1, i) - lowest(values as number[], i - halfP + 1, i)) / halfP;
    if (n1 + n2 > 0 && n3 > 0) {
      out[i] = 1 + (Math.log(n1 + n2) - Math.log(n3)) / Math.log(2);
    }
  }
  return out;
}

// ============================================================
// 4. Volatility and Dispersion Studies (Separate Panes)
// ============================================================

export function atr(highs: number[], lows: number[], closes: number[], period = 14): N[] {
  const trVals: number[] = [highs[0] - lows[0]];
  for (let i = 1; i < closes.length; i++) {
    trVals.push(trueRange(highs[i], lows[i], closes[i - 1]));
  }
  return wilderSmooth(trVals, period);
}

export function normalizedAtr(highs: number[], lows: number[], closes: number[], period = 14): N[] {
  const atrVals = atr(highs, lows, closes, period);
  return atrVals.map((v, i) => v != null && closes[i] !== 0 ? ((v as number) / closes[i]) * 100 : null);
}

export function historicalVolatility(values: number[], period: number): N[] {
  const returns: number[] = [0];
  for (let i = 1; i < values.length; i++) {
    returns.push(values[i - 1] !== 0 ? Math.log(values[i] / values[i - 1]) : 0);
  }
  const out: N[] = new Array(values.length).fill(null);
  for (let i = period; i < values.length; i++) {
    out[i] = stddev(returns, i - period + 1, i) * Math.sqrt(252) * 100;
  }
  return out;
}

export function realizedVolatility(values: number[], period: number): N[] {
  return historicalVolatility(values, period);
}

export function parkinsonVolatility(highs: number[], lows: number[], period: number): N[] {
  const out: N[] = new Array(highs.length).fill(null);
  for (let i = period - 1; i < highs.length; i++) {
    let s = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const hl = lows[j] > 0 ? Math.log(highs[j] / lows[j]) : 0;
      s += hl * hl;
    }
    out[i] = Math.sqrt(s / (4 * period * Math.log(2))) * Math.sqrt(252) * 100;
  }
  return out;
}

export function garmanKlassVolatility(opens: number[], highs: number[], lows: number[], closes: number[], period: number): N[] {
  const out: N[] = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    let s = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const u = highs[j] > 0 ? Math.log(highs[j] / opens[j]) : 0;
      const d = lows[j] > 0 ? Math.log(lows[j] / opens[j]) : 0;
      const c = closes[j] > 0 ? Math.log(closes[j] / opens[j]) : 0;
      s += 0.5 * (u - d) ** 2 - (2 * Math.log(2) - 1) * c ** 2;
    }
    out[i] = Math.sqrt(Math.abs(s / period)) * Math.sqrt(252) * 100;
  }
  return out;
}

export function rogersSatchellVolatility(opens: number[], highs: number[], lows: number[], closes: number[], period: number): N[] {
  const out: N[] = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    let s = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const hc = Math.log(highs[j] / closes[j]);
      const ho = Math.log(highs[j] / opens[j]);
      const lc = Math.log(lows[j] / closes[j]);
      const lo = Math.log(lows[j] / opens[j]);
      s += hc * ho + lc * lo;
    }
    out[i] = Math.sqrt(Math.abs(s / period)) * Math.sqrt(252) * 100;
  }
  return out;
}

export function rollingStdDev(values: number[], period: number): N[] {
  const out: N[] = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    out[i] = stddev(values, i - period + 1, i);
  }
  return out;
}

export function volatilityRatio(values: number[], shortPeriod: number, longPeriod: number): N[] {
  const shortVol = historicalVolatility(values, shortPeriod);
  const longVol = historicalVolatility(values, longPeriod);
  return values.map((_, i) => {
    if (shortVol[i] != null && longVol[i] != null && (longVol[i] as number) !== 0)
      return (shortVol[i] as number) / (longVol[i] as number);
    return null;
  });
}

export function rollingRange(highs: number[], lows: number[], period: number): N[] {
  const out: N[] = new Array(highs.length).fill(null);
  for (let i = period - 1; i < highs.length; i++) {
    out[i] = highest(highs, i - period + 1, i) - lowest(lows, i - period + 1, i);
  }
  return out;
}

export function bollingerWidth(values: number[], period: number, k = 2): N[] {
  const bb = bollingerBands(values, period, k);
  return values.map((_, i) => {
    if (bb.upper[i] != null && bb.lower[i] != null && bb.mid[i] != null && (bb.mid[i] as number) !== 0)
      return ((bb.upper[i] as number) - (bb.lower[i] as number)) / (bb.mid[i] as number);
    return null;
  });
}

export function bollingerPercentB(values: number[], period: number, k = 2): N[] {
  const bb = bollingerBands(values, period, k);
  return values.map((v, i) => {
    if (bb.upper[i] != null && bb.lower[i] != null) {
      const w = (bb.upper[i] as number) - (bb.lower[i] as number);
      return w !== 0 ? (v - (bb.lower[i] as number)) / w : 0.5;
    }
    return null;
  });
}

export function keltnerWidth(closes: number[], highs: number[], lows: number[], emaPeriod = 20, atrPeriod = 10, mult = 1.5): N[] {
  const kc = keltnerChannel(closes, highs, lows, emaPeriod, atrPeriod, mult);
  return closes.map((_, i) => {
    if (kc.upper[i] != null && kc.lower[i] != null && kc.mid[i] != null && (kc.mid[i] as number) !== 0)
      return ((kc.upper[i] as number) - (kc.lower[i] as number)) / (kc.mid[i] as number);
    return null;
  });
}

export function volOfVol(values: number[], volPeriod: number, vovPeriod: number): N[] {
  const vol = historicalVolatility(values, volPeriod);
  const volNums = vol.map(v => v ?? 0);
  return rollingStdDev(volNums, vovPeriod);
}

// ============================================================
// 5. Volume, Turnover, Accumulation-Distribution (Separate Panes)
// ============================================================

export function volumeMovingAverage(volumes: number[], period: number): N[] {
  return sma(volumes, period);
}

export function volumeOscillator(volumes: number[], fast = 5, slow = 20): N[] {
  const emaFast = ema(volumes, fast);
  const emaSlow = ema(volumes, slow);
  return volumes.map((_, i) => {
    if (emaFast[i] != null && emaSlow[i] != null && (emaSlow[i] as number) !== 0)
      return (((emaFast[i] as number) - (emaSlow[i] as number)) / (emaSlow[i] as number)) * 100;
    return null;
  });
}

export function obv(closes: number[], volumes: number[]): number[] {
  const out: number[] = [0];
  for (let i = 1; i < closes.length; i++) {
    if (closes[i] > closes[i - 1]) out.push(out[i - 1] + volumes[i]);
    else if (closes[i] < closes[i - 1]) out.push(out[i - 1] - volumes[i]);
    else out.push(out[i - 1]);
  }
  return out;
}

export function accumulationDistribution(highs: number[], lows: number[], closes: number[], volumes: number[]): number[] {
  const out: number[] = [];
  let cumAd = 0;
  for (let i = 0; i < closes.length; i++) {
    const hl = highs[i] - lows[i];
    const mfm = hl !== 0 ? ((closes[i] - lows[i]) - (highs[i] - closes[i])) / hl : 0;
    cumAd += mfm * volumes[i];
    out.push(cumAd);
  }
  return out;
}

export function chaikinMoneyFlow(highs: number[], lows: number[], closes: number[], volumes: number[], period = 20): N[] {
  const out: N[] = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    let mfvSum = 0, volSum = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const hl = highs[j] - lows[j];
      const mfm = hl !== 0 ? ((closes[j] - lows[j]) - (highs[j] - closes[j])) / hl : 0;
      mfvSum += mfm * volumes[j];
      volSum += volumes[j];
    }
    out[i] = volSum !== 0 ? mfvSum / volSum : 0;
  }
  return out;
}

export function chaikinOscillator(highs: number[], lows: number[], closes: number[], volumes: number[], fast = 3, slow = 10): N[] {
  const ad = accumulationDistribution(highs, lows, closes, volumes);
  const emaFast = ema(ad, fast);
  const emaSlow = ema(ad, slow);
  return ad.map((_, i) => {
    if (emaFast[i] != null && emaSlow[i] != null) return (emaFast[i] as number) - (emaSlow[i] as number);
    return null;
  });
}

export function mfi(highs: number[], lows: number[], closes: number[], volumes: number[], period = 14): N[] {
  const tp = closes.map((c, i) => (highs[i] + lows[i] + c) / 3);
  const out: N[] = new Array(closes.length).fill(null);
  for (let i = period; i < closes.length; i++) {
    let posMf = 0, negMf = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const mf = tp[j] * volumes[j];
      if (tp[j] > tp[j - 1]) posMf += mf;
      else negMf += mf;
    }
    out[i] = negMf !== 0 ? 100 - 100 / (1 + posMf / negMf) : 100;
  }
  return out;
}

export function eom(highs: number[], lows: number[], volumes: number[], period = 14): N[] {
  const raw: number[] = [0];
  for (let i = 1; i < highs.length; i++) {
    const dm = ((highs[i] + lows[i]) / 2) - ((highs[i - 1] + lows[i - 1]) / 2);
    const br = volumes[i] !== 0 ? (volumes[i] / 1e6) / (highs[i] - lows[i] || 1) : 0;
    raw.push(br !== 0 ? dm / br : 0);
  }
  return sma(raw, period);
}

export function forceIndex(closes: number[], volumes: number[], period = 13): N[] {
  const raw: number[] = [0];
  for (let i = 1; i < closes.length; i++) {
    raw.push((closes[i] - closes[i - 1]) * volumes[i]);
  }
  return ema(raw, period);
}

export function klingerOscillator(highs: number[], lows: number[], closes: number[], volumes: number[], fast = 34, slow = 55, signal = 13): { klinger: N[]; signal: N[] } {
  const hlc = closes.map((c, i) => highs[i] + lows[i] + c);
  const trend: number[] = [0];
  for (let i = 1; i < hlc.length; i++) trend.push(hlc[i] > hlc[i - 1] ? 1 : -1);
  const vf = volumes.map((v, i) => v * trend[i]);
  const emaFast = ema(vf, fast);
  const emaSlow = ema(vf, slow);
  const klinger: N[] = vf.map((_, i) => {
    if (emaFast[i] != null && emaSlow[i] != null) return (emaFast[i] as number) - (emaSlow[i] as number);
    return null;
  });
  const kNums = klinger.map(v => v ?? 0);
  const sig = ema(kNums, signal);
  return { klinger, signal: sig };
}

export function pvt(closes: number[], volumes: number[]): number[] {
  const out: number[] = [0];
  for (let i = 1; i < closes.length; i++) {
    const ret = closes[i - 1] !== 0 ? (closes[i] - closes[i - 1]) / closes[i - 1] : 0;
    out.push(out[i - 1] + ret * volumes[i]);
  }
  return out;
}

export function nvi(closes: number[], volumes: number[]): number[] {
  const out: number[] = [1000];
  for (let i = 1; i < closes.length; i++) {
    if (volumes[i] < volumes[i - 1]) {
      const ret = closes[i - 1] !== 0 ? (closes[i] - closes[i - 1]) / closes[i - 1] : 0;
      out.push(out[i - 1] * (1 + ret));
    } else {
      out.push(out[i - 1]);
    }
  }
  return out;
}

export function pvi(closes: number[], volumes: number[]): number[] {
  const out: number[] = [1000];
  for (let i = 1; i < closes.length; i++) {
    if (volumes[i] > volumes[i - 1]) {
      const ret = closes[i - 1] !== 0 ? (closes[i] - closes[i - 1]) / closes[i - 1] : 0;
      out.push(out[i - 1] * (1 + ret));
    } else {
      out.push(out[i - 1]);
    }
  }
  return out;
}

export function volumeRoc(volumes: number[], period: number): N[] {
  return roc(volumes, period);
}

export function relativeVolume(volumes: number[], period: number): N[] {
  const avg = sma(volumes, period);
  return volumes.map((v, i) => avg[i] != null && (avg[i] as number) !== 0 ? v / (avg[i] as number) : null);
}

// ============================================================
// 6. Order Flow & Tape Indicators (from trade data)
// ============================================================

export interface TradeData {
  timestamp: number;
  price: number;
  quantity: number;
  side: 'BUY' | 'SELL' | null;
}

export function tradeImbalance(trades: TradeData[], period: number): N[] {
  const out: N[] = new Array(trades.length).fill(null);
  for (let i = period - 1; i < trades.length; i++) {
    let buy = 0, sell = 0;
    for (let j = i - period + 1; j <= i; j++) {
      if (trades[j].side === 'BUY') buy += trades[j].quantity;
      else if (trades[j].side === 'SELL') sell += trades[j].quantity;
    }
    const total = buy + sell;
    out[i] = total !== 0 ? (buy - sell) / total : 0;
  }
  return out;
}

export function cumulativeDelta(trades: TradeData[]): number[] {
  const out: number[] = [];
  let cum = 0;
  for (const t of trades) {
    if (t.side === 'BUY') cum += t.quantity;
    else if (t.side === 'SELL') cum -= t.quantity;
    out.push(cum);
  }
  return out;
}

export function signedVolume(trades: TradeData[], period: number): N[] {
  const signed = trades.map(t => t.side === 'BUY' ? t.quantity : t.side === 'SELL' ? -t.quantity : 0);
  const out: N[] = new Array(trades.length).fill(null);
  for (let i = period - 1; i < trades.length; i++) {
    out[i] = sum(signed, i - period + 1, i);
  }
  return out;
}

export function tradeBurstIntensity(trades: TradeData[], period: number): N[] {
  const out: N[] = new Array(trades.length).fill(null);
  for (let i = period - 1; i < trades.length; i++) {
    let vol = 0;
    for (let j = i - period + 1; j <= i; j++) vol += trades[j].quantity;
    out[i] = vol;
  }
  return out;
}

export function interTradeTime(trades: TradeData[]): N[] {
  const out: N[] = [null];
  for (let i = 1; i < trades.length; i++) {
    out.push(trades[i].timestamp - trades[i - 1].timestamp);
  }
  return out;
}

export function tradeArrivalRate(trades: TradeData[], period: number): N[] {
  const out: N[] = new Array(trades.length).fill(null);
  for (let i = period - 1; i < trades.length; i++) {
    const timeSpan = trades[i].timestamp - trades[i - period + 1].timestamp;
    out[i] = timeSpan > 0 ? (period / timeSpan) * 1000 : period;
  }
  return out;
}

export function tradeDirectionPersistence(trades: TradeData[], period: number): N[] {
  const out: N[] = new Array(trades.length).fill(null);
  for (let i = period - 1; i < trades.length; i++) {
    let streak = 1;
    for (let j = i; j > i - period + 1; j--) {
      if (trades[j].side === trades[j - 1].side && trades[j].side != null) streak++;
      else break;
    }
    out[i] = streak / period;
  }
  return out;
}

// ============================================================
// 7. Spread & Microstructure (from order book data)
// ============================================================

export interface BookSnapshot {
  timestamp: number;
  bestBid: number;
  bestAsk: number;
  bidDepth: number;
  askDepth: number;
  midPrice: number;
  weightedMid?: number;
  microprice?: number;
  topImbalance?: number;
  top3Imbalance?: number;
}

export function spreadSeries(books: BookSnapshot[]): number[] {
  return books.map(b => b.bestAsk - b.bestBid);
}

export function relativeSpread(books: BookSnapshot[]): N[] {
  return books.map(b => b.midPrice !== 0 ? ((b.bestAsk - b.bestBid) / b.midPrice) * 100 : null);
}

export function spreadZScore(books: BookSnapshot[], period: number): N[] {
  const spreads = spreadSeries(books);
  const out: N[] = new Array(books.length).fill(null);
  for (let i = period - 1; i < books.length; i++) {
    const m = mean(spreads, i - period + 1, i);
    const s = stddev(spreads, i - period + 1, i);
    out[i] = s !== 0 ? (spreads[i] - m) / s : 0;
  }
  return out;
}

export function micropriceDev(books: BookSnapshot[]): N[] {
  return books.map(b => b.microprice != null ? b.microprice - b.midPrice : null);
}

export function weightedMidDev(books: BookSnapshot[]): N[] {
  return books.map(b => b.weightedMid != null ? b.weightedMid - b.midPrice : null);
}

export function topOfBookImbalance(books: BookSnapshot[]): N[] {
  return books.map(b => b.topImbalance ?? null);
}

export function bidDepthSeries(books: BookSnapshot[]): number[] {
  return books.map(b => b.bidDepth);
}

export function askDepthSeries(books: BookSnapshot[]): number[] {
  return books.map(b => b.askDepth);
}

export function totalDepthSeries(books: BookSnapshot[]): number[] {
  return books.map(b => b.bidDepth + b.askDepth);
}

export function depthRatio(books: BookSnapshot[]): N[] {
  return books.map(b => (b.bidDepth + b.askDepth) !== 0 ? b.bidDepth / (b.bidDepth + b.askDepth) : null);
}

export function bookPressureScore(books: BookSnapshot[]): N[] {
  return books.map(b => {
    const total = b.bidDepth + b.askDepth;
    return total !== 0 ? (b.bidDepth - b.askDepth) / total : null;
  });
}

// ============================================================
// 8. Execution Quality (from fill data)
// ============================================================

export interface FillData {
  timestamp: number;
  price: number;
  quantity: number;
  side: 'BUY' | 'SELL';
  midAtFill?: number;
  aggressive?: boolean;
}

export function slippage(fills: FillData[]): N[] {
  return fills.map(f => {
    if (f.midAtFill == null) return null;
    return f.side === 'BUY' ? f.price - f.midAtFill : f.midAtFill - f.price;
  });
}

export function effectiveSpread(fills: FillData[]): N[] {
  return fills.map(f => {
    if (f.midAtFill == null) return null;
    return 2 * Math.abs(f.price - f.midAtFill);
  });
}

export function inventoryCurve(fills: FillData[]): number[] {
  const out: number[] = [];
  let pos = 0;
  for (const f of fills) {
    pos += f.side === 'BUY' ? f.quantity : -f.quantity;
    out.push(pos);
  }
  return out;
}

export function realizedPnlCurve(fills: FillData[]): number[] {
  const out: number[] = [];
  let pos = 0, avgEntry = 0, realized = 0;
  for (const f of fills) {
    const signed = f.side === 'BUY' ? f.quantity : -f.quantity;
    const oldPos = pos;
    const newPos = oldPos + signed;
    if (oldPos === 0) {
      avgEntry = f.price;
    } else if ((oldPos > 0 && signed > 0) || (oldPos < 0 && signed < 0)) {
      avgEntry = (avgEntry * Math.abs(oldPos) + f.price * Math.abs(signed)) / Math.abs(newPos);
    } else {
      const closed = Math.min(Math.abs(signed), Math.abs(oldPos));
      realized += oldPos > 0 ? (f.price - avgEntry) * closed : (avgEntry - f.price) * closed;
      if (Math.abs(signed) > Math.abs(oldPos)) avgEntry = f.price;
    }
    pos = newPos;
    out.push(realized);
  }
  return out;
}

// ============================================================
// 9. Regime & Composite Signals (Separate Panes)
// ============================================================

export function trendScore(closes: number[], period = 20): N[] {
  const smaVals = sma(closes, period);
  const er = efficiencyRatio(closes, period);
  return closes.map((c, i) => {
    if (smaVals[i] == null || er[i] == null) return null;
    const direction = c > (smaVals[i] as number) ? 1 : -1;
    return direction * (er[i] as number) * 100;
  });
}

export function meanReversionScore(closes: number[], period = 20, k = 2): N[] {
  const bb = bollingerBands(closes, period, k);
  return closes.map((c, i) => {
    if (bb.upper[i] == null || bb.lower[i] == null || bb.mid[i] == null) return null;
    const width = (bb.upper[i] as number) - (bb.lower[i] as number);
    return width !== 0 ? ((c - (bb.mid[i] as number)) / (width / 2)) * -100 : 0;
  });
}

export function volatilityRegimeScore(closes: number[], shortPeriod = 10, longPeriod = 50): N[] {
  const shortVol = historicalVolatility(closes, shortPeriod);
  const longVol = historicalVolatility(closes, longPeriod);
  return closes.map((_, i) => {
    if (shortVol[i] == null || longVol[i] == null || (longVol[i] as number) === 0) return null;
    return ((shortVol[i] as number) / (longVol[i] as number) - 1) * 100;
  });
}

export function fairValueDeviation(closes: number[], period = 20): N[] {
  const vwapVals = sma(closes, period);
  return closes.map((c, i) => {
    if (vwapVals[i] == null) return null;
    return (c - (vwapVals[i] as number)) / (vwapVals[i] as number) * 100;
  });
}
