// Small pure helpers for reading text in images. Shared by the background worker
// (which checks what a page asks for) and the offscreen OCR document.
(() => {
  const MAX_REGIONS = 4;
  const MIN_REGION = 24;           // CSS pixels
  const MIN_CONFIDENCE = 40;       // Tesseract's mean word confidence, 0-100
  const MIN_LETTERS = 12;
  const MAX_TEXT = 2000;
  const MAX_CANVAS = 4096;         // device pixels on the longest side after upscaling

  // Check the regions a page sends before any screenshot is cropped.
  function validRegions(regions) {
    if (!Array.isArray(regions) || !regions.length || regions.length > MAX_REGIONS) return null;
    const clean = [];
    for (const region of regions) {
      if (!region || typeof region !== 'object') return null;
      const { id, x, y, w, h } = region;
      if (typeof id !== 'string' || !id || id.length > 16) return null;
      if (![x, y, w, h].every(Number.isFinite) || x < 0 || y < 0 || w < MIN_REGION || h < MIN_REGION) return null;
      clean.push({ id, x, y, w, h });
    }
    return clean;
  }

  // Map a region in CSS pixels to screenshot pixels. Small text is enlarged,
  // because OCR reads poorly below about 20 pixels per line.
  function planCrop(region, imageWidth, imageHeight, viewportWidth) {
    if (!(viewportWidth > 0) || !(imageWidth > 0) || !(imageHeight > 0)) return null;
    const scale = imageWidth / viewportWidth;
    const sx = Math.max(0, Math.floor(region.x * scale));
    const sy = Math.max(0, Math.floor(region.y * scale));
    const sw = Math.min(imageWidth - sx, Math.ceil(region.w * scale));
    const sh = Math.min(imageHeight - sy, Math.ceil(region.h * scale));
    if (sw < MIN_REGION || sh < MIN_REGION) return null;
    const wanted = Math.max(1, Math.min(3, 2 / scale));
    const upscale = Math.min(wanted, MAX_CANVAS / Math.max(sw, sh));
    return { sx, sy, sw, sh, upscale: Math.max(upscale, 0.25) };
  }

  // Keep only text the OCR engine is reasonably sure of.
  function cleanText(text, confidence) {
    const flat = String(text || '').replace(/\s+/g, ' ').trim();
    if (!(confidence >= MIN_CONFIDENCE)) return '';
    if ((flat.match(/[\p{L}\p{N}]/gu) || []).length < MIN_LETTERS) return '';
    return flat.slice(0, MAX_TEXT);
  }

  // Describe a decoded QR code: web links are checked as links; UPI payment
  // codes are described in words so the payment rules can see them.
  function describeQr(data) {
    const value = String(data || '').trim();
    if (!value || value.length > 2048) return null;
    if (/^https?:\/\/[^\s]+$/i.test(value)) return { url: value };
    if (/^upi:\/\/pay\?/i.test(value)) {
      let params;
      try { params = new URL(value).searchParams; } catch { return null; }
      const payee = (params.get('pn') || params.get('pa') || 'an unknown payee').slice(0, 80);
      const amount = params.get('am');
      return { text: `This QR code starts a UPI payment to ${payee}${amount ? ` of ${amount.slice(0, 20)}` : ''}. Scanning it sends money; it never receives money.` };
    }
    return null;
  }

  globalThis.SentinelOcr = { MAX_REGIONS, validRegions, planCrop, cleanText, describeQr };
})();
