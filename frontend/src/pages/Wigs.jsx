import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import Icon from "../components/icons.jsx";
import TryOn from "../components/TryOn.jsx";
import WigArt from "../components/WigArt.jsx";
import { ErrorBox, Spinner, useFetch } from "../components/ui.jsx";

// Nuancier (reprend la grille de couleurs de la maquette) -> familles du catalogue
const SWATCHES = [
  ["#E3D6BE", "blond", "Platine"], ["#D1A95E", "blond", "Doré"], ["#C9A063", "blond", "Miel"], ["#B9A68A", "blond", "Cendré"],
  ["#A06A3A", "chatain", "Caramel"], ["#8A5A33", "chatain", "Châtain doré"], ["#7B5738", "chatain", "Châtain clair"], ["#5C3A24", "chatain", "Châtain"],
  ["#A2502A", "roux", "Cuivré"], ["#9C4A22", "roux", "Cannelle"], ["#7A2E1F", "roux", "Auburn"], ["#553624", "brun", "Moka"],
  ["#4A2C1D", "brun", "Chocolat"], ["#3B2519", "brun", "Expresso"], ["#4B3A31", "brun", "Brun cendré"], ["#241C1A", "noir", "Noir doux"],
  ["#141011", "noir", "Noir de jais"], ["#9D9A99", "gris", "Gris perle"], ["#B8B8BC", "gris", "Argenté"], ["#D9D6D2", "gris", "Blanc neige"],
];
const LENGTHS = ["court", "mi-long", "long"];
const SHAPES = { ovale: "Ovale", rond: "Rond", carre: "Carré", coeur: "En cœur", allonge: "Allongé" };

export default function Wigs() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [colors, setColors] = useState([]);
  const [length, setLength] = useState(1);
  const [texture, setTexture] = useState("");
  const [budget, setBudget] = useState("");
  const [shapeOverride, setShapeOverride] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [camera, setCamera] = useState(false);
  const catalog = useFetch("/wigs/catalog");
  const [tryWig, setTryWig] = useState(null);       // null = fermé ; id = perruque à essayer
  const tryRef = useRef(null);
  const openTryOn = (id) => {
    setTryWig(id || "first");
    setTimeout(() => tryRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const first = useRef(true);

  const families = [...new Set(colors.map((i) => SWATCHES[i][1]))];
  const prefs = () => ({ color_families: families, length: LENGTHS[length], texture: texture || undefined,
    budget: budget ? Number(budget) : undefined, face_shape_override: shapeOverride || undefined });

  useEffect(() => {
    api("/wigs/last").then((d) => {
      if (d.analysis) setResult({ id: d.id, analysis: d.analysis, recommendations: d.recommendations, fromHistory: true });
    }).catch(() => {});
    return () => stopCamera();
  }, []);

  // Recalcul instantané quand les préférences changent (sans renvoyer la photo)
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (!result?.id) return;
    const t = setTimeout(() => {
      api("/wigs/recommend", { method: "POST", body: { analysis_id: result.id, preferences: prefs() } })
        .then((d) => setResult((r) => ({ ...r, recommendations: d.recommendations }))).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colors, length, texture, budget, shapeOverride]);

  const pick = (f) => {
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
    setError(null);
  };

  const startCamera = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: 960 } });
      streamRef.current = s;
      setCamera(true);
      setTimeout(() => { if (videoRef.current) videoRef.current.srcObject = s; }, 0);
    } catch {
      setError("Impossible d'accéder à la caméra. Autorisez-la dans le navigateur ou importez une photo.");
    }
  };
  function stopCamera() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setCamera(false);
  }
  const snap = () => {
    const v = videoRef.current;
    const c = document.createElement("canvas");
    c.width = v.videoWidth; c.height = v.videoHeight;
    const ctx = c.getContext("2d");
    ctx.translate(c.width, 0); ctx.scale(-1, 1);
    ctx.drawImage(v, 0, 0);
    c.toBlob((b) => { pick(new File([b], "camera.jpg", { type: "image/jpeg" })); stopCamera(); }, "image/jpeg", 0.92);
  };

  const analyze = async () => {
    if (!file) return setError("Ajoutez d'abord une photo de face.");
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("photo", file);
    form.append("preferences", JSON.stringify(prefs()));
    try {
      setShapeOverride("");
      setResult(await api("/wigs/analyze", { method: "POST", form }));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const a = result?.analysis;
  const rec = result?.recommendations;
  const tryable = catalog.data?.items?.filter((w) => w.tryon) || [];
  return (
    <div className="wigs">
      {!tryWig && tryable.length > 0 && (
        <div className="card soft row-between">
          <p className="small"><strong>Nouveau :</strong> essayez les perruques sur votre visage, en direct, avec la caméra.</p>
          <button className="btn primary small" onClick={() => openTryOn(null)}>Essayage virtuel</button>
        </div>
      )}
      {tryWig && catalog.data && (
        <div ref={tryRef}>
          <TryOn key={tryWig} wigs={catalog.data.items} initialId={tryWig === "first" ? rec?.items?.find((w) => w.tryon)?.id : tryWig}
            onClose={() => setTryWig(null)} />
        </div>
      )}
      <div className="wig-layout">
        <section className="card wig-input">
          <h2>Votre photo</h2>
          <div className="photo-zone">
            {camera ? (
              <video ref={videoRef} autoPlay playsInline muted className="mirror" />
            ) : a?.annotated_image && !preview ? (
              <img src={a.annotated_image} alt="Analyse du visage" />
            ) : preview ? (
              <img src={preview} alt="Aperçu" />
            ) : (
              <div className="photo-placeholder"><img src="/silhouette.svg" alt="" /><p>Photo de face, visage dégagé, lumière naturelle.</p></div>
            )}
          </div>
          <div className="actions">
            {camera ? (
              <>
                <button className="btn primary" onClick={snap}><Icon name="camera" size={18} /> Prendre la photo</button>
                <button className="btn ghost" onClick={stopCamera}>Annuler</button>
              </>
            ) : (
              <>
                <label className="btn ghost file-btn"><Icon name="upload" size={18} /> Importer
                  <input type="file" accept="image/*" onChange={(e) => pick(e.target.files[0])} hidden />
                </label>
                <button className="btn ghost" onClick={startCamera}><Icon name="camera" size={18} /> Caméra</button>
              </>
            )}
          </div>
          <p className="tiny muted">La photo est analysée sur le serveur BreastFriend puis supprimée ; seules les mesures sont conservées.</p>

          <h3>Ce que vous préférez</h3>
          <p className="field-label">Couleur <span className="muted small">(plusieurs choix possibles)</span></p>
          <div className="swatches" role="group" aria-label="Couleurs">
            {SWATCHES.map(([hex, fam, name], i) => (
              <button key={hex} className={`swatch ${colors.includes(i) ? "on" : ""}`} style={{ "--c": hex }} title={name}
                aria-label={name} aria-pressed={colors.includes(i)}
                onClick={() => setColors(colors.includes(i) ? colors.filter((x) => x !== i) : [...colors, i])} />
            ))}
          </div>
          <label className="field-label" htmlFor="len">Longueur : <strong>{LENGTHS[length]}</strong></label>
          <input id="len" type="range" min="0" max="2" step="1" value={length} onChange={(e) => setLength(Number(e.target.value))} className="range" />
          <div className="row2">
            <label>Texture
              <select value={texture} onChange={(e) => setTexture(e.target.value)}>
                <option value="">Peu importe</option><option value="lisse">Lisse</option><option value="ondule">Ondulée</option><option value="boucle">Bouclée</option>
              </select>
            </label>
            <label>Budget max (DT)
              <input type="number" min="0" step="50" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="Aucun" />
            </label>
          </div>
          <ErrorBox>{error}</ErrorBox>
          <button className="btn primary wide" onClick={analyze} disabled={busy || !file}>
            {busy ? "Analyse en cours…" : result?.fromHistory && !file ? "Nouvelle photo pour relancer l'analyse" : "Analyser et recommander"}
          </button>
        </section>

        <section className="wig-results">
          {busy && <Spinner label="Analyse du visage…" />}
          {!a && !busy && (
            <div className="card soft"><h3>Comment ça marche</h3>
              <p className="small">La vision par ordinateur détecte votre visage, mesure la largeur du front, des pommettes et de la mâchoire ainsi que la longueur du visage, puis estime votre teint et son sous-ton. Nous combinons ces mesures avec vos préférences pour classer notre catalogue de perruques.</p>
            </div>
          )}
          {a && (
            <div className="card analysis">
              {preview && a.annotated_image && <img className="annotated" src={a.annotated_image} alt="Mesures du visage" />}
              <div className="analysis-facts">
                <div>
                  <span className="field-label">Forme du visage</span>
                  <select value={shapeOverride || a.face_shape} onChange={(e) => setShapeOverride(e.target.value === a.face_shape ? "" : e.target.value)} aria-label="Corriger la forme du visage">
                    {Object.entries(SHAPES).map(([k, v]) => <option key={k} value={k}>{v}{k === a.face_shape ? " (détecté)" : ""}</option>)}
                  </select>
                  <span className="tiny muted">fiabilité estimée {Math.round(a.confidence * 100)} %</span>
                </div>
                <div>
                  <span className="field-label">Teint</span>
                  <span className="skin"><i style={{ background: a.skin.hex }} /> {a.skin.depth}, sous-ton {a.skin.undertone_label}</span>
                </div>
              </div>
              <p className="tip">{rec?.tip}</p>
              {a.warnings?.length > 0 && <ul className="warnings">{a.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
            </div>
          )}
          {rec && (
            <>
              <h3 className="rec-title">Nos suggestions pour un visage {rec.face_shape_label.toLowerCase()}</h3>
              <div className="wig-list">
                {rec.items.map((w, i) => (
                  <article key={w.id} className={`wig-item ${i === 0 ? "best" : ""}`}>
                    <WigArt wig={w} />
                    <div className="wig-info">
                      <div className="wig-top">
                        <h4>{w.name}</h4>
                        <span className="match" title="Compatibilité">{w.score} %</span>
                      </div>
                      <p className="small muted">{w.style} · {w.length} · {w.color_name} · {w.material}</p>
                      <ul className="reasons">{w.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                      {w.cautions.map((c) => <p key={c} className="caution small">{c}</p>)}
                      <p className="price">{w.price_tnd} DT</p>
                      {w.tryon && <button className="btn ghost small" onClick={() => openTryOn(w.id)}>Essayer en direct</button>}
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
