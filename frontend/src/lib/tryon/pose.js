// Repères MediaPipe Face Landmarker (478 points, coordonnées normalisées 0..1) -> pose
// de la tête -> transformation du calque de perruque. Fonctions pures, testées dans
// frontend/tests/tryon.test.mjs.

export const LM = {
  foreheadTop: 10,      // milieu du haut du front (≈ ligne frontale)
  chin: 152,
  faceRight: 234,       // bord du visage côté droit de la personne (à gauche de l'image)
  faceLeft: 454,
  eyeOuterR: 33,
  eyeOuterL: 263,
  noseTip: 1,
  browR: 105,
  browL: 334,
};

// Contour du visage (ordre MediaPipe FACEMESH_FACE_OVAL)
export const FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
  152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109];

const px = (lm, i, w, h) => ({ x: lm[i].x * w, y: lm[i].y * h });
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Pose 2D de la tête en pixels de l'image (non mise en miroir). */
export function headPose(landmarks, width, height) {
  const p = (i) => px(landmarks, i, width, height);
  const right = p(LM.faceRight), left = p(LM.faceLeft);
  const eyeR = p(LM.eyeOuterR), eyeL = p(LM.eyeOuterL);
  const roll = Math.atan2(eyeL.y - eyeR.y, eyeL.x - eyeR.x);          // inclinaison de la tête
  const faceWidth = dist(right, left);
  const ex = { x: Math.cos(roll), y: Math.sin(roll) };                 // axe des yeux
  const mid = { x: (right.x + left.x) / 2, y: (right.y + left.y) / 2 };
  const nose = p(LM.noseTip);
  // rotation gauche/droite : décalage du nez par rapport au milieu du visage, le long de l'axe des yeux
  const yaw = Math.asin(clamp(((nose.x - mid.x) * ex.x + (nose.y - mid.y) * ex.y) / (faceWidth / 2), -0.95, 0.95));
  const top = p(LM.foreheadTop), chin = p(LM.chin);
  const brows = { x: (p(LM.browR).x + p(LM.browL).x) / 2, y: (p(LM.browR).y + p(LM.browL).y) / 2 };
  return {
    anchor: top,
    faceWidth,
    faceHeight: dist(top, chin),
    roll,
    yaw,
    brows,
    oval: FACE_OVAL.map(p),
  };
}

/** Réglages manuels exprimés dans le repère du visage (suivent l'inclinaison de la tête). */
export const DEFAULT_ADJUST = { dx: 0, dy: 0, scale: 1, rotate: 0 };

/**
 * Transformation du calque : position (px), échelle, rotation (rad), compression horizontale.
 * asset : { width, height, anchor: {x, y} (normalisés), face_width (fraction de la largeur) }
 */
export function wigTransform(pose, asset, adjust = DEFAULT_ADJUST) {
  const base = pose.faceWidth / (asset.face_width * asset.width);
  const scale = base * adjust.scale;
  const rotation = pose.roll + (adjust.rotate * Math.PI) / 180;
  // décalages manuels : dx vers la droite de l'image, dy vers le haut, en fractions de visage
  const ux = { x: Math.cos(pose.roll), y: Math.sin(pose.roll) };
  const uy = { x: Math.sin(pose.roll), y: -Math.cos(pose.roll) };
  const x = pose.anchor.x + (adjust.dx * ux.x + adjust.dy * uy.x) * pose.faceWidth;
  const y = pose.anchor.y + (adjust.dx * ux.y + adjust.dy * uy.y) * pose.faceWidth;
  // un calque 2D ne peut pas tourner en profondeur : légère compression quand la tête pivote
  const squeeze = 1 - 0.18 * Math.abs(Math.sin(pose.yaw));
  return {
    x, y, rotation, scaleX: scale * squeeze, scaleY: scale,
    originX: asset.anchor.x * asset.width, originY: asset.anchor.y * asset.height,
  };
}

/**
 * Masque d'occultation : la zone du visage sous les sourcils. Les pixels du calque qui y
 * tombent sont effacés (les mèches passent derrière les joues, la frange reste sur le front).
 */
export function occlusionPolygon(pose, browMargin = 0.04) {
  const c = Math.cos(-pose.roll), s = Math.sin(-pose.roll);
  const toLocal = (q) => ({ x: (q.x - pose.anchor.x) * c - (q.y - pose.anchor.y) * s,
                            y: (q.x - pose.anchor.x) * s + (q.y - pose.anchor.y) * c });
  const toImage = (q) => ({ x: pose.anchor.x + q.x * c + q.y * s, y: pose.anchor.y - q.x * s + q.y * c });
  const browY = toLocal(pose.brows).y - browMargin * pose.faceWidth;
  return pose.oval.map(toLocal).map((q) => toImage({ x: q.x, y: Math.max(q.y, browY) }));
}

/** Tête hors champ ou trop petite / trop tournée pour un rendu crédible ? */
export function poseQuality(pose, width) {
  if (pose.faceWidth < width * 0.12) return "far";
  if (Math.abs(pose.yaw) > 0.7) return "turned";
  return "ok";
}
