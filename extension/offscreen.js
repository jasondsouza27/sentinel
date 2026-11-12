// Runs in Chrome's hidden offscreen document. It reads text (Tesseract.js) and
// QR codes (jsQR) in regions of a screenshot. Everything runs on this computer,
// from files bundled in the extension; only the text found goes back to the
// background worker, and the screenshot is dropped afterwards.
(() => {
  const base = chrome.runtime.getURL('vendor/tesseract/');
  const START_TIMEOUT_MS = 45000, READ_TIMEOUT_MS = 20000;
  let engine = null;

  // Tesseract.js can wait forever if its engine fails to start, so bound each step.
  function within(promise, ms, what) {
    let timer;
    return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${what} timed out`)), ms); })])
      .finally(() => clearTimeout(timer));
  }

  function ocr() {
    engine ||= within(Tesseract.createWorker('eng', 1 /* LSTM only */, {
      workerPath: base + 'worker.min.js',
      corePath: base + 'core',
      langPath: base + 'lang',
      workerBlobURL: false,
      cacheMethod: 'none',
    }), START_TIMEOUT_MS, 'Starting OCR').catch(error => { engine = null; throw error; });
    return engine;
  }

  async function bitmap(dataUrl) {
    const blob = await (await fetch(dataUrl)).blob();
    return createImageBitmap(blob);
  }

  async function read({ dataUrl, viewportWidth, regions }) {
    const image = await bitmap(dataUrl);
    const worker = await ocr();
    const results = [];
    try {
      for (const region of regions) {
        const crop = SentinelOcr.planCrop(region, image.width, image.height, viewportWidth);
        if (!crop) { results.push({ id: region.id, text: '', qr: null }); continue; }
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(crop.sw * crop.upscale));
        canvas.height = Math.max(1, Math.round(crop.sh * crop.upscale));
        const context = canvas.getContext('2d', { willReadFrequently: true });
        context.imageSmoothingQuality = 'high';
        context.drawImage(image, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, canvas.width, canvas.height);
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
        const code = jsQR(pixels.data, canvas.width, canvas.height, { inversionAttempts: 'attemptBoth' });
        const { data } = await within(worker.recognize(canvas), READ_TIMEOUT_MS, 'Reading an image');
        results.push({ id: region.id, text: SentinelOcr.cleanText(data.text, data.confidence), qr: code ? SentinelOcr.describeQr(code.data) : null });
      }
    } finally {
      image.close();
    }
    return { results };
  }

  chrome.runtime.onMessage.addListener((message, sender, reply) => {
    if (message?.target !== 'sentinel-offscreen' || sender.id !== chrome.runtime.id || message.type !== 'ocr') return false;
    read(message).then(reply, error => reply({ error: `Text in images could not be read: ${error?.message || error}` }));
    return true;
  });
})();
