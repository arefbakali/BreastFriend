// node --test tests/        (depuis frontend/)
import assert from "node:assert/strict";
import test from "node:test";
import { OneEuroFilter, createPoseSmoother } from "../src/lib/tryon/oneEuro.js";
import { FACE_OVAL, LM, headPose, occlusionPolygon, wigTransform } from "../src/lib/tryon/pose.js";

const W = 640, H = 480;
const ASSET = { width: 1024, height: 1400, anchor: { x: 0.5, y: 0.2571 }, face_width: 0.42 };

/** Visage synthétique : centre (cx, cy) px, largeur fw px, inclinaison roll, pivot yaw. */
function face({ cx = 320, cy = 250, fw = 200, roll = 0, yaw = 0 } = {}) {
  const lm = Array.from({ length: 478 }, () => ({ x: cx / W, y: cy / H, z: 0 }));
  const put = (i, lx, ly) => {        // coordonnées locales (unités de visage), y vers le bas
    const x = cx + (lx * Math.cos(roll) - ly * Math.sin(roll)) * fw;
    const y = cy + (lx * Math.sin(roll) + ly * Math.cos(roll)) * fw;
    lm[i] = { x: x / W, y: y / H, z: 0 };
  };
  FACE_OVAL.forEach((i, k) => {
    const a = (k / FACE_OVAL.length) * 2 * Math.PI;
    put(i, 0.5 * Math.sin(a), -0.62 * Math.cos(a));
  });
  put(LM.foreheadTop, 0, -0.62);
  put(LM.chin, 0, 0.62);
  put(LM.faceRight, -0.5, 0);
  put(LM.faceLeft, 0.5, 0);
  put(LM.eyeOuterR, -0.3, -0.12);
  put(LM.eyeOuterL, 0.3, -0.12);
  put(LM.browR, -0.22, -0.24);
  put(LM.browL, 0.22, -0.24);
  put(LM.noseTip, 0.5 * Math.sin(yaw), 0.1);
  return lm;
}

const close = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b}`);

test("position, taille et inclinaison suivent le visage", () => {
  const p = headPose(face({ cx: 300, cy: 260, fw: 200 }), W, H);
  close(p.faceWidth, 200, 0.5, "largeur");
  close(p.anchor.x, 300, 0.5, "ancrage x");
  close(p.anchor.y, 260 - 0.62 * 200, 0.5, "ancrage y");
  close(p.roll, 0, 1e-6, "inclinaison nulle");

  const near = headPose(face({ fw: 300 }), W, H);
  const far = headPose(face({ fw: 150 }), W, H);
  const tn = wigTransform(near, ASSET), tf = wigTransform(far, ASSET);
  close(tn.scaleY / tf.scaleY, 2, 1e-6, "échelle proportionnelle à la distance");
  // la largeur tempe-tempe du calque, une fois mise à l'échelle, égale celle du visage
  close(ASSET.face_width * ASSET.width * tn.scaleY, 300, 1e-6, "calage de la largeur");

  const tilted = headPose(face({ roll: 0.3 }), W, H);
  close(tilted.roll, 0.3, 1e-6, "inclinaison");
  close(wigTransform(tilted, ASSET).rotation, 0.3, 1e-6, "rotation du calque");
});

test("rotation gauche/droite estimée et compression horizontale", () => {
  const p = headPose(face({ yaw: 0.4 }), W, H);
  close(p.yaw, 0.4, 0.01, "yaw");
  const t = wigTransform(p, ASSET);
  assert.ok(t.scaleX < t.scaleY, "compression horizontale quand la tête pivote");
  assert.ok(t.scaleX > 0.85 * t.scaleY, "compression modérée");
});

test("réglages manuels appliqués dans le repère du visage", () => {
  const p = headPose(face({ roll: Math.PI / 2 }), W, H);
  const base = wigTransform(p, ASSET);
  const up = wigTransform(p, ASSET, { dx: 0, dy: 0.1, scale: 1.1, rotate: 5 });
  // tête couchée à 90° : « vers le haut du visage » = vers +x dans l'image
  close(up.x - base.x, 0.1 * p.faceWidth, 1e-6, "haut du visage");
  close(up.y - base.y, 0, 1e-6, "pas de dérive verticale");
  close(up.scaleY / base.scaleY, 1.1, 1e-9, "échelle manuelle");
  close(up.rotation - base.rotation, (5 * Math.PI) / 180, 1e-9, "rotation manuelle");
});

test("masque d'occultation : sous les sourcils seulement, suit l'inclinaison", () => {
  for (const roll of [0, 0.35]) {
    const p = headPose(face({ roll }), W, H);
    const poly = occlusionPolygon(p);
    const c = Math.cos(-roll), s = Math.sin(-roll);
    const localY = (q) => (q.x - p.anchor.x) * s + (q.y - p.anchor.y) * c;
    const browY = localY(p.brows) - 0.04 * p.faceWidth;
    assert.equal(poly.length, FACE_OVAL.length);
    assert.ok(poly.every((q) => localY(q) >= browY - 1e-6), "aucun point au-dessus des sourcils (frange préservée)");
    assert.ok(Math.max(...poly.map(localY)) > 0.9 * p.faceWidth, "descend jusqu'au menton");
  }
});

test("One Euro : réduit le tremblement sans retard notable", () => {
  let seed = 7;
  const noise = () => ((seed = (seed * 16807) % 2147483647) / 2147483647 - 0.5);
  const f = new OneEuroFilter({ minCutoff: 1.4, beta: 6 });
  let rawVar = 0, outVar = 0;
  for (let i = 0; i < 300; i++) {                  // tête immobile, repères bruités (30 fps)
    const raw = 1 + noise() * 0.02;
    const out = f.filter(raw, i / 30);
    if (i > 30) { rawVar += (raw - 1) ** 2; outVar += (out - 1) ** 2; }
  }
  assert.ok(outVar < rawVar * 0.25, `tremblement divisé par > 4 (${(rawVar / outVar).toFixed(1)}x)`);

  const g = new OneEuroFilter({ minCutoff: 1.4, beta: 6 });
  for (let i = 0; i < 30; i++) g.filter(0, i / 30);
  let t = 30, v = 0;                               // mouvement rapide : 1 largeur de visage en 1/3 s
  for (let k = 1; k <= 10; k++) v = g.filter(k / 10, t++ / 30);
  assert.ok(v > 0.85, `suit le mouvement rapide (${v.toFixed(2)} après 10 images)`);
});

test("lissage de pose indépendant de la résolution", () => {
  const s1 = createPoseSmoother(), s2 = createPoseSmoother();
  let a, b;
  for (let i = 0; i < 20; i++) {
    const lm = face({ fw: 200, cx: 300 + i });      // mêmes repères normalisés, caméra 2x plus définie
    a = s1.smooth(headPose(lm, W, H), i / 30);
    b = s2.smooth(headPose(lm, W * 2, H * 2), i / 30);
  }
  close(b.anchor.x / 2, a.anchor.x, 1e-6, "même comportement à 2x la résolution");
});
