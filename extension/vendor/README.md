# Bundled libraries

Chrome extensions can't load code from the internet, so the OCR and QR libraries used by
"Read text in images" are copied here from npm. They run only in `offscreen.html`.

| File | Package | Licence |
|---|---|---|
| `tesseract/tesseract.min.js`, `tesseract/worker.min.js` | `tesseract.js@6.0.1` (`dist/`) | Apache-2.0 (`tesseract/LICENSE-tesseract.js.md`) |
| `tesseract/core/tesseract-core-simd-lstm.wasm.js`, `tesseract/core/tesseract-core-lstm.wasm.js` | `tesseract.js-core@6.0.0` | Apache-2.0 (`tesseract/core/LICENSE-tesseract.js-core`) |
| `tesseract/lang/eng.traineddata.gz` | `@tesseract.js-data/eng@1.0.0` (`4.0.0_best_int/`) | MIT (package licence); Tesseract's trained data is Apache-2.0 |
| `jsqr/jsQR.js` | `jsqr@1.4.0` (`dist/`) | Apache-2.0 (`jsqr/LICENSE`) |

SHA-256:

```
bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859  jsqr/jsQR.js
775a35df6f2ae100e02609443e6bd5cafcd07983dd6175454ca4a432a7730687  tesseract/core/tesseract-core-lstm.wasm.js
9d7c43fb206dc9f48475228b46bf35f888fa9e6259da2e67d5a75c77049f2dc7  tesseract/core/tesseract-core-simd-lstm.wasm.js
45b4cb346724ac1774f1c36f42f182b887bcdb28ebe63e6fff90ac41f3fcff91  tesseract/lang/eng.traineddata.gz
10fff78484067759c43028a02a72d76d0b90eb17302bb23b58a9ec5410bc928b  tesseract/tesseract.min.js
38645599043239c0eb6db08a6504a92dcdc292200535f3e9339cd77c4443b842  tesseract/worker.min.js
```

To update them, run `npm pack` for each package in an empty folder, copy the same files and
update this table and the checksums. Only the LSTM cores are bundled, because the worker is
started in LSTM-only mode.
