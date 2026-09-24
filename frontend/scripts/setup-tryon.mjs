// Prépare l'essayage virtuel pour un fonctionnement 100 % local (sans CDN) :
//   1. copie les fichiers WASM de @mediapipe/tasks-vision dans public/mediapipe/wasm
//   2. télécharge le modèle face_landmarker.task (~3,6 Mo) dans public/models (une fois)
// Lancé automatiquement après « npm install » ; sans réseau, l'application utilisera le
// CDN au premier essayage (sauf VITE_LOCAL_ONLY=true).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const wasmSrc = path.join(root, "node_modules", "@mediapipe", "tasks-vision", "wasm");
const wasmDst = path.join(root, "public", "mediapipe", "wasm");
const model = path.join(root, "public", "models", "face_landmarker.task");
const MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

if (fs.existsSync(wasmSrc)) {
  fs.mkdirSync(wasmDst, { recursive: true });
  for (const f of fs.readdirSync(wasmSrc)) fs.copyFileSync(path.join(wasmSrc, f), path.join(wasmDst, f));
  console.log(`[essayage] WASM MediaPipe copié dans ${path.relative(root, wasmDst)}`);
} else {
  console.warn("[essayage] @mediapipe/tasks-vision non installé : lancez « npm install ».");
}

if (fs.existsSync(model) && fs.statSync(model).size > 1_000_000) {
  console.log("[essayage] Modèle de suivi déjà présent.");
} else {
  try {
    const res = await fetch(MODEL_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    fs.mkdirSync(path.dirname(model), { recursive: true });
    fs.writeFileSync(model, Buffer.from(await res.arrayBuffer()));
    console.log(`[essayage] Modèle téléchargé : ${path.relative(root, model)}`);
  } catch (err) {
    console.warn(`[essayage] Téléchargement du modèle impossible (${err.message}). ` +
      "Il sera chargé depuis le CDN au premier essayage, ou relancez « npm run setup:tryon ».");
  }
}
