import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPoseSmoother } from "../lib/tryon/oneEuro.js";
import { DEFAULT_ADJUST, headPose, occlusionPolygon, poseQuality, wigTransform } from "../lib/tryon/pose.js";
import { Canvas2DWigRenderer } from "../lib/tryon/renderer2d.js";
import { detect, loadFaceTracker } from "../lib/tryon/tracker.js";
import Icon from "./icons.jsx";
import WigArt from "./WigArt.jsx";

// Essayage virtuel en temps réel :
//   caméra -> vidéo -> repères du visage (MediaPipe, dans le navigateur) -> pose de la tête
//   -> lissage One Euro -> transformation du calque -> rendu Canvas au-dessus de la vidéo.
// Aucune image n'est envoyée au serveur. Une capture n'est créée que sur demande et
// uniquement téléchargée sur l'appareil.

const images = new Map();        // calques déjà décodés (pas de rechargement en changeant de modèle)
function loadImage(src) {
  if (!images.has(src)) {
    images.set(src, new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => { images.delete(src); reject(new Error("Calque de perruque introuvable.")); };
      img.src = src;
    }));
  }
  return images.get(src);
}

const CAMERA_ERRORS = {
  NotAllowedError: "Accès à la caméra refusé. Autorisez la caméra pour ce site dans votre navigateur, puis réessayez.",
  NotFoundError: "Aucune caméra détectée sur cet appareil.",
  NotReadableError: "La caméra est déjà utilisée par une autre application.",
  OverconstrainedError: "La caméra ne prend pas en charge ce format.",
};
const STEP = 0.02;
const LOST_FADE_MS = 350;

export default function TryOn({ wigs, initialId, onClose }) {
  const usable = wigs.filter((w) => w.tryon);
  const [wigId, setWigId] = useState(initialId && usable.some((w) => w.id === initialId) ? initialId : usable[0]?.id);
  const [phase, setPhase] = useState("idle");      // idle | camera | model | running | error
  const [message, setMessage] = useState("");
  const [adjust, setAdjust] = useState(DEFAULT_ADJUST);
  const [showWig, setShowWig] = useState(true);
  const [occlude, setOcclude] = useState(true);
  const [opacity, setOpacity] = useState(1);
  const [hint, setHint] = useState(null);
  const [fps, setFps] = useState(0);

  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const stream = useRef(null);
  const raf = useRef(0);
  const state = useRef({ adjust, showWig, occlude, opacity, image: null, asset: null });
  state.current = { ...state.current, adjust, showWig, occlude, opacity };
  const wig = usable.find((w) => w.id === wigId);

  useEffect(() => {
    if (!wig) return;
    state.current.asset = wig.tryon;
    state.current.image = null;
    loadImage(wig.tryon.src).then((img) => { if (state.current.asset === wig.tryon) state.current.image = img; })
      .catch((err) => setHint(err.message));
  }, [wig]);

  const stop = useCallback(() => {
    cancelAnimationFrame(raf.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  }, []);
  useEffect(() => stop, [stop]);

  const start = async () => {
    setMessage("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setPhase("error");
      setMessage("La caméra n'est accessible que via une connexion sécurisée (https ou localhost).");
      return;
    }
    setPhase("camera");
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
      const video = videoRef.current;
      video.srcObject = stream.current;
      await video.play();
      setPhase("model");
      const tracker = await loadFaceTracker(setMessage);
      setMessage("");
      setPhase("running");
      loop(tracker);
    } catch (err) {
      stop();
      setPhase("error");
      setMessage(CAMERA_ERRORS[err.name] || err.message || "Impossible de démarrer l'essayage.");
    }
  };

  const loop = (tracker) => {
    const video = videoRef.current;
    const renderer = new Canvas2DWigRenderer(canvasRef.current);
    const smoother = createPoseSmoother();
    let lastVideoTime = -1, pose = null, lastSeen = 0, frames = 0, fpsT = performance.now();
    const tick = () => {
      raf.current = requestAnimationFrame(tick);
      if (video.readyState < 2) return;
      const w = video.videoWidth, h = video.videoHeight;
      renderer.resize(w, h);
      const now = performance.now();
      if (video.currentTime !== lastVideoTime) {          // une détection par nouvelle image vidéo
        lastVideoTime = video.currentTime;
        const lm = detect(tracker, video, now);
        if (lm) {
          const raw = headPose(lm, w, h);
          if (now - lastSeen > 500) smoother.reset();       // visage retrouvé : pas de glissement
          pose = smoother.smooth(raw, now / 1000);
          lastSeen = now;
          const q = poseQuality(pose, w);
          setHint(q === "far" ? "Rapprochez-vous de la caméra." : q === "turned" ? "Tournez-vous davantage face à la caméra." : null);
        } else if (now - lastSeen > 1000) {
          setHint("Visage non détecté : placez-vous face à la caméra, bien éclairée.");
        }
        frames += 1;
        if (now - fpsT > 1000) { setFps(Math.round((frames * 1000) / (now - fpsT))); frames = 0; fpsT = now; }
      }
      const s = state.current;
      const lost = now - lastSeen;
      // visage perdu : on garde la perruque 120 ms (clignement, flou), puis fondu de LOST_FADE_MS
      const fade = !pose ? 0 : lost < 120 ? 1 : Math.max(0, 1 - (lost - 120) / LOST_FADE_MS);
      renderer.draw({
        video,
        image: s.image,
        transform: pose && s.asset ? wigTransform(pose, s.asset, s.adjust) : null,
        occlusion: pose && s.occlude ? occlusionPolygon(pose) : null,
        opacity: s.opacity * fade,
        showWig: s.showWig,
      });
    };
    tick();
  };

  const capture = () => {
    canvasRef.current.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `essayage-${wig?.name || "perruque"}.png`.replace(/\s+/g, "-");
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, "image/png");
  };

  const nudge = (k, v) => setAdjust((a) => ({ ...a, [k]: +(a[k] + v).toFixed(3) }));
  const running = phase === "running";

  if (!usable.length) {
    return <div className="card"><p>Aucune perruque ne dispose encore d'un calque d'essayage valide.</p></div>;
  }
  return (
    <section className="card tryon" aria-label="Essayage virtuel en direct">
      <div className="row-between">
        <h2>Essayage virtuel en direct</h2>
        {onClose && <button className="link small" onClick={() => { stop(); onClose(); }}>Fermer</button>}
      </div>
      <div className="tryon-layout">
        <div className="tryon-stage">
          <video ref={videoRef} playsInline muted className="tryon-video" />
          <canvas ref={canvasRef} className="tryon-canvas" data-testid="tryon-canvas" hidden={!running} />
          {!running && (
            <div className="tryon-overlay">
              {phase === "idle" && (
                <>
                  <p><strong>Voyez la perruque sur votre visage, en direct.</strong></p>
                  <p className="small">Le suivi du visage fonctionne entièrement dans votre navigateur : aucune image n'est envoyée à BreastFriend ni enregistrée. Une photo n'est créée que si vous cliquez sur « Capturer », et elle reste sur votre appareil.</p>
                  <button className="btn primary" onClick={start}><Icon name="camera" size={18} /> Activer la caméra</button>
                </>
              )}
              {(phase === "camera" || phase === "model") && (
                <>
                  <div className="spinner" role="status"><span className="dot" /> <span className="dot" /> <span className="dot" /></div>
                  <p className="small">{phase === "camera" ? "Ouverture de la caméra…" : message || "Chargement du modèle de suivi…"}</p>
                </>
              )}
              {phase === "error" && (
                <>
                  <p className="form-error">{message}</p>
                  <button className="btn ghost" onClick={start}>Réessayer</button>
                </>
              )}
            </div>
          )}
          {running && hint && <div className="tryon-hint" role="status">{hint}</div>}
          {running && <span className="tryon-fps" aria-hidden="true">{fps} img/s</span>}
        </div>

        <div className="tryon-controls">
          {wig?.tryon.quality === "illustrative" && (
            <p className="remote-note">Calque illustratif : il montre la coupe, la longueur et la couleur, mais n'est pas une photo du produit réel.</p>
          )}
          <p className="field-label">Modèle</p>
          <div className="tryon-picker" role="listbox" aria-label="Choisir une perruque">
            {usable.map((w) => (
              <button key={w.id} role="option" aria-selected={w.id === wigId} className={`tryon-wig ${w.id === wigId ? "on" : ""}`}
                onClick={() => setWigId(w.id)} title={`${w.name} — ${w.color_name}`}>
                <WigArt wig={w} />
                <span className="tiny">{w.name}</span>
              </button>
            ))}
          </div>
          <p className="field-label">Ajustement</p>
          <div className="tryon-pad" role="group" aria-label="Déplacer la perruque">
            <span />
            <button className="icon-btn" onClick={() => nudge("dy", STEP)} aria-label="Monter">▲</button>
            <span />
            <button className="icon-btn" onClick={() => nudge("dx", -STEP)} aria-label="Vers la gauche">◀</button>
            <button className="icon-btn small" onClick={() => setAdjust(DEFAULT_ADJUST)} aria-label="Réinitialiser">⟲</button>
            <button className="icon-btn" onClick={() => nudge("dx", STEP)} aria-label="Vers la droite">▶</button>
            <span />
            <button className="icon-btn" onClick={() => nudge("dy", -STEP)} aria-label="Descendre">▼</button>
            <span />
          </div>
          <label className="small">Taille ({Math.round(adjust.scale * 100)} %)
            <input type="range" className="range" min="0.8" max="1.25" step="0.01" value={adjust.scale}
              onChange={(e) => setAdjust({ ...adjust, scale: Number(e.target.value) })} />
          </label>
          <label className="small">Rotation ({adjust.rotate}°)
            <input type="range" className="range" min="-15" max="15" step="1" value={adjust.rotate}
              onChange={(e) => setAdjust({ ...adjust, rotate: Number(e.target.value) })} />
          </label>
          <label className="small">Opacité ({Math.round(opacity * 100)} %)
            <input type="range" className="range" min="0.4" max="1" step="0.05" value={opacity}
              onChange={(e) => setOpacity(Number(e.target.value))} />
          </label>
          <label className="small check"><input type="checkbox" checked={occlude} onChange={(e) => setOcclude(e.target.checked)} /> Mèches derrière le visage</label>
          <div className="actions">
            <button className="btn ghost" onClick={() => setShowWig(!showWig)} disabled={!running} aria-pressed={!showWig}>
              {showWig ? "Voir sans perruque" : "Voir avec perruque"}
            </button>
            <button className="btn primary" onClick={capture} disabled={!running}><Icon name="camera" size={16} /> Capturer</button>
          </div>
          {running && <button className="link small" onClick={() => { stop(); setPhase("idle"); }}>Arrêter la caméra</button>}
        </div>
      </div>
    </section>
  );
}
