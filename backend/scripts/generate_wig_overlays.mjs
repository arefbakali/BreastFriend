// Génère des calques d'essayage ILLUSTRATIFS (PNG RGBA transparents) pour les perruques du
// catalogue qui n'ont pas de vraie photo détourée. Ils respectent la spécification décrite
// dans docs/WIG_ASSETS.md (point d'ancrage, largeur du visage, ouverture transparente), afin
// que le suivi fonctionne dès maintenant ; ils ne prétendent PAS être photoréalistes et sont
// signalés « illustratif » dans l'interface. Remplacez-les par de vrais calques quand ils existent.
//
//   node backend/scripts/generate_wig_overlays.mjs        (nécessite le module sharp : npm install sharp)
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
// sharp : installé localement (npm i sharp), dans frontend/node_modules, ou dossier indiqué par SHARP_DIR
let sharp;
for (const candidate of ["sharp", path.join(here, "..", "..", "frontend", "node_modules", "sharp"), process.env.SHARP_DIR]) {
  if (!candidate) continue;
  try { sharp = require(candidate); break; } catch { /* essai suivant */ }
}
if (!sharp) {
  console.error("Module « sharp » introuvable : lancez « npm install sharp » (ou définissez SHARP_DIR).");
  process.exit(1);
}
const catalogPath = path.join(here, "..", "vision", "wigs_catalog.json");
const outDir = path.join(here, "..", "static", "wigs", "tryon");
fs.mkdirSync(outDir, { recursive: true });

// Géométrie commune (pixels) — reportée dans les métadonnées du catalogue
const W = 1024, H = 1400;
const FACE_W = 430;              // distance tempe-tempe (repères 234–454) dans l'image
const AX = W / 2, AY = 360;      // ancrage = milieu de la ligne frontale (repère 10)

function shade(hex, f) {
  const n = parseInt(hex.slice(1), 16);
  const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.max(0, Math.min(255, Math.round(f >= 0 ? v + (255 - v) * f : v * (1 + f)))));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

function rng(seed) {
  let s = seed;
  return () => ((s = (s * 16807) % 2147483647) / 2147483647);
}

function hairSvg(wig) {
  const base = wig.color_hex;
  const dark = shade(base, -0.35), light = shade(base, 0.28);
  const r = rng([...wig.id].reduce((a, c) => a * 31 + c.charCodeAt(0), 7));
  const half = FACE_W / 2;
  const bottom = { court: AY + 0.62 * FACE_W, "mi-long": AY + 1.45 * FACE_W, long: AY + 2.25 * FACE_W }[wig.length] || AY + 1.2 * FACE_W;
  const side = half + (wig.texture === "boucle" ? 95 : wig.texture === "ondule" ? 75 : 58);
  const crownTop = AY - 0.42 * FACE_W - (wig.texture === "boucle" ? 40 : 0);
  const wave = wig.texture === "ondule" ? 22 : wig.texture === "boucle" ? 34 : 6;

  // silhouette : dôme + côtés jusqu'à la longueur choisie
  const pts = [];
  const steps = 14;
  for (let i = 0; i <= steps; i++) {                       // côté gauche, de bas en haut
    const t = i / steps, y = bottom - (bottom - (AY + 40)) * t;
    const x = AX - side - Math.sin(t * Math.PI * 3) * wave * (1 - t * 0.5) + (wig.length === "court" ? t * 10 : -t * 10);
    pts.push([x, y]);
  }
  const dome = (dir) => {
    const out = [];
    for (let i = 0; i <= 12; i++) {
      const a = Math.PI * (dir > 0 ? i / 12 : 1 - i / 12);
      out.push([AX - Math.cos(a) * (side + 6), AY + 40 - Math.sin(a) * (AY + 40 - crownTop)]);
    }
    return out;
  };
  pts.push(...dome(1));
  for (let i = steps; i >= 0; i--) {                       // côté droit, de haut en bas
    const t = i / steps, y = bottom - (bottom - (AY + 40)) * t;
    const x = AX + side + Math.sin(t * Math.PI * 3 + 1) * wave * (1 - t * 0.5) - (wig.length === "court" ? t * 10 : -t * 10);
    pts.push([x, y]);
  }
  const outline = `M${pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L")} Z`;

  // mèches
  let strands = "";
  const n = wig.texture === "boucle" ? 0 : 70;
  for (let i = 0; i < n; i++) {
    const sideSign = i % 2 ? 1 : -1;
    const x0 = AX + sideSign * r() * side * 0.9;
    const y0 = crownTop + 30 + r() * 60;
    const x1 = AX + sideSign * (half + 10 + r() * (side - half));
    const y1 = bottom - r() * 60;
    const cx = x0 + sideSign * (60 + r() * 60);
    strands += `<path d="M${x0.toFixed(0)},${y0.toFixed(0)} Q${cx.toFixed(0)},${(AY + 30).toFixed(0)} ${x1.toFixed(0)},${y1.toFixed(0)}" stroke="${r() > 0.5 ? light : dark}" stroke-opacity="${(0.18 + r() * 0.25).toFixed(2)}" stroke-width="${(2 + r() * 3).toFixed(1)}" fill="none"/>`;
  }
  let curls = "";
  if (wig.texture === "boucle") {
    for (let i = 0; i < 260; i++) {
      const x = AX + (r() * 2 - 1) * (side + 10), y = crownTop + 20 + r() * (bottom - crownTop - 30);
      curls += `<circle cx="${x.toFixed(0)}" cy="${y.toFixed(0)}" r="${(10 + r() * 16).toFixed(0)}" fill="none" stroke="${r() > 0.5 ? light : dark}" stroke-opacity="0.35" stroke-width="4"/>`;
    }
  }
  // frange
  let fringe = "";
  if (wig.fringe) {
    const top = AY - 0.16 * FACE_W, low = AY + 0.2 * FACE_W;
    const n = 7;
    let edge = "";
    for (let i = n; i >= 0; i--) {             // bord inférieur festonné, de droite à gauche
      const x = AX - half * 0.98 + (half * 1.96 * i) / n;
      const y = low - Math.abs(i - n * 0.35) * 5 + (i % 2 ? 10 : 0);
      edge += ` L${x.toFixed(0)},${y.toFixed(0)}`;
    }
    fringe = `<path d="M${AX - half - 20},${AY + 30} Q${AX - half * 0.4},${top} ${AX + half * 0.3},${top + 6}
      Q${AX + half + 10},${top + 20} ${AX + half + 20},${AY + 30} L${AX + half * 0.98},${low}${edge} Z"
      fill="url(#g)" filter="url(#soft)"/>`;
  }
  // ouverture du visage (transparente) : du haut du front au menton, entre les tempes
  const faceHole = `<ellipse cx="${AX}" cy="${AY + 0.66 * FACE_W}" rx="${half * 0.97}" ry="${0.72 * FACE_W}" fill="black"/>
    <rect x="${AX - half * 0.97}" y="${AY + 0.66 * FACE_W}" width="${half * 1.94}" height="${H}" fill="black"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${dark}"/><stop offset="0.25" stop-color="${base}"/>
      <stop offset="0.7" stop-color="${shade(base, 0.08)}"/><stop offset="1" stop-color="${shade(base, -0.15)}"/>
    </linearGradient>
    <radialGradient id="shine" cx="0.42" cy="0.18" r="0.5"><stop offset="0" stop-color="#fff" stop-opacity="0.25"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
    <mask id="m"><rect width="${W}" height="${H}" fill="white"/>${faceHole}</mask>
    <clipPath id="clip"><path d="${outline}"/></clipPath>
    <filter id="soft"><feGaussianBlur stdDeviation="1.4"/></filter>
  </defs>
  <g mask="url(#m)" filter="url(#soft)">
    <path d="${outline}" fill="url(#g)"/>
    <path d="${outline}" fill="url(#shine)"/>
    <g clip-path="url(#clip)">${strands}${curls}</g>
  </g>
  ${fringe}
</svg>`;
}

const catalog = JSON.parse(fs.readFileSync(catalogPath, "utf8"));
for (const wig of catalog) {
  const file = `${wig.id}.png`;
  await sharp(Buffer.from(hairSvg(wig))).png({ compressionLevel: 9 }).toFile(path.join(outDir, file));
  wig.tryon = {
    type: "2d",
    src: `/static/wigs/tryon/${file}`,
    width: W,
    height: H,
    anchor: { x: +(AX / W).toFixed(4), y: +(AY / H).toFixed(4) },
    face_width: +(FACE_W / W).toFixed(4),
    quality: "illustrative",
  };
}
fs.writeFileSync(catalogPath, `${JSON.stringify(catalog, null, 2)}\n`);
console.log(`${catalog.length} calques illustratifs écrits dans ${outDir}`);
