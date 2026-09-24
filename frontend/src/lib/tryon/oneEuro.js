// Filtre « One Euro » (Casiez, Roussel & Vogel, CHI 2012).
// Lisse fortement quand la tête est immobile (supprime le tremblement des repères) et
// presque plus quand elle bouge vite (pas de retard perceptible) : la fréquence de coupure
// augmente avec la vitesse. Une moyenne exponentielle fixe ne peut pas faire les deux.
const alpha = (cutoff, dt) => {
  const tau = 1 / (2 * Math.PI * cutoff);
  return 1 / (1 + tau / dt);
};

export class OneEuroFilter {
  constructor({ minCutoff = 1.0, beta = 0.0, dCutoff = 1.0 } = {}) {
    Object.assign(this, { minCutoff, beta, dCutoff });
    this.reset();
  }

  reset() {
    this.x = null;
    this.dx = 0;
    this.t = null;
  }

  filter(value, tSeconds) {
    if (this.x === null) {
      this.x = value;
      this.t = tSeconds;
      return value;
    }
    const dt = Math.max(1e-3, tSeconds - this.t);
    this.t = tSeconds;
    const rawDx = (value - this.x) / dt;
    this.dx += alpha(this.dCutoff, dt) * (rawDx - this.dx);
    const cutoff = this.minCutoff + this.beta * Math.abs(this.dx);
    this.x += alpha(cutoff, dt) * (value - this.x);
    return this.x;
  }
}

/** Filtre pour un angle (radians) : évite le saut à ±π. */
export class AngleFilter extends OneEuroFilter {
  filter(value, t) {
    if (this.x !== null) {
      while (value - this.x > Math.PI) value -= 2 * Math.PI;
      while (value - this.x < -Math.PI) value += 2 * Math.PI;
    }
    return super.filter(value, t);
  }
}

/** Ensemble de filtres pour la pose de la tête. Réglages exprimés en fractions de la
 *  largeur du visage pour être indépendants de la résolution de la caméra. */
export function createPoseSmoother() {
  const pos = { minCutoff: 1.4, beta: 6.0 };      // positions normalisées par la largeur du visage
  const f = {
    x: new OneEuroFilter(pos), y: new OneEuroFilter(pos),
    w: new OneEuroFilter({ minCutoff: 1.0, beta: 3.0 }),
    roll: new AngleFilter({ minCutoff: 1.2, beta: 0.6 }),
    yaw: new AngleFilter({ minCutoff: 1.0, beta: 0.4 }),
  };
  return {
    reset() { Object.values(f).forEach((x) => x.reset()); },
    smooth(pose, t) {
      const unit = pose.faceWidth;               // on filtre en unités « visage »
      const w = f.w.filter(pose.faceWidth / unit, t) * unit;
      return {
        ...pose,
        anchor: { x: f.x.filter(pose.anchor.x / unit, t) * unit, y: f.y.filter(pose.anchor.y / unit, t) * unit },
        faceWidth: w,
        roll: f.roll.filter(pose.roll, t),
        yaw: f.yaw.filter(pose.yaw, t),
      };
    },
  };
}
