// Suivi du visage dans le navigateur (MediaPipe Face Landmarker, 478 repères).
// Les images de la caméra ne quittent jamais l'appareil : aucun envoi au serveur.
// Le modèle est chargé une seule fois par session (promesse partagée), jamais par image.
export const MEDIAPIPE_VERSION = "0.10.14";     // doit correspondre à package.json
const LOCAL = { wasm: "/mediapipe/wasm", model: "/models/face_landmarker.task" };
const CDN = {
  wasm: `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MEDIAPIPE_VERSION}/wasm`,
  model: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
};
const LOCAL_ONLY = import.meta.env?.VITE_LOCAL_ONLY === "true";

let shared = null;

async function exists(url) {
  try {
    const r = await fetch(url, { method: "HEAD" });
    // le serveur de dev renvoie index.html pour un fichier absent : on vérifie le type
    return r.ok && !(r.headers.get("content-type") || "").includes("text/html");
  } catch {
    return false;
  }
}

async function create(onStatus) {
  const { FaceLandmarker, FilesetResolver } = await import("@mediapipe/tasks-vision");
  const sources = [];
  if (await exists(`${LOCAL.wasm}/vision_wasm_internal.js`) && await exists(LOCAL.model)) sources.push(["local", LOCAL]);
  if (!LOCAL_ONLY) sources.push(["cdn", CDN]);
  if (!sources.length) {
    throw new Error("Modèle de suivi absent : lancez « npm run setup:tryon » (fichiers locaux requis en mode LOCAL_ONLY).");
  }
  let lastError;
  for (const [name, src] of sources) {
    onStatus?.(name === "local" ? "Chargement du modèle de suivi…" : "Téléchargement du modèle de suivi (une seule fois)…");
    try {
      const fileset = await FilesetResolver.forVisionTasks(src.wasm);
      for (const delegate of ["GPU", "CPU"]) {
        try {
          const landmarker = await FaceLandmarker.createFromOptions(fileset, {
            baseOptions: { modelAssetPath: src.model, delegate },
            runningMode: "VIDEO",
            numFaces: 1,
            minFaceDetectionConfidence: 0.5,
            minTrackingConfidence: 0.5,
          });
          return { landmarker, source: name, delegate };
        } catch (err) {
          lastError = err;
          console.warn(`Face Landmarker : délégué ${delegate} indisponible`, err);
        }
      }
    } catch (err) {
      lastError = err;
      console.warn(`Face Landmarker : source ${name} indisponible`, err);
    }
  }
  throw new Error(`Impossible de charger le suivi du visage (${lastError?.message || "erreur inconnue"}).`);
}

export function loadFaceTracker(onStatus) {
  if (!shared) {
    shared = create(onStatus).catch((err) => {
      shared = null;                      // un nouvel essai reste possible
      throw err;
    });
  }
  return shared;
}

/** Repères du visage pour l'image courante de la vidéo, ou null. */
export function detect(tracker, video, timestampMs) {
  const res = tracker.landmarker.detectForVideo(video, timestampMs);
  return res?.faceLandmarks?.[0] || null;
}
