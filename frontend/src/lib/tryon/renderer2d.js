// Rendu 2D (Canvas) : vidéo + calque de perruque transformé + occultation du visage.
// Interface commune aux moteurs de rendu : resize(w, h), draw(frame), dispose().
// Un futur moteur 3D (WebGL / three.js, calques glTF) implémentera la même interface
// et recevra la même pose ; TryOn choisit le moteur selon asset.type.
export class Canvas2DWigRenderer {
  kind = "2d";

  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.layer = document.createElement("canvas");
    this.lctx = this.layer.getContext("2d");
  }

  resize(w, h) {
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = this.layer.width = w;
      this.canvas.height = this.layer.height = h;
    }
  }

  /**
   * frame : { video, image, transform, occlusion (polygone px) | null, opacity 0..1,
   *           showWig, mirror, feather (px) }
   */
  draw({ video, image, transform, occlusion, opacity = 1, showWig = true, mirror = true, feather = 6 }) {
    const { ctx, lctx, canvas } = this;
    const w = canvas.width, h = canvas.height;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, w, h);
    if (mirror) ctx.setTransform(-1, 0, 0, 1, w, 0);      // effet miroir, comme un selfie
    ctx.drawImage(video, 0, 0, w, h);
    if (!showWig || !image || !transform || opacity <= 0) return;

    lctx.setTransform(1, 0, 0, 1, 0, 0);
    lctx.globalCompositeOperation = "source-over";
    lctx.filter = "none";
    lctx.clearRect(0, 0, w, h);
    lctx.translate(transform.x, transform.y);
    lctx.rotate(transform.rotation);
    lctx.scale(transform.scaleX, transform.scaleY);
    lctx.drawImage(image, -transform.originX, -transform.originY);
    lctx.setTransform(1, 0, 0, 1, 0, 0);
    if (occlusion?.length) {
      // les mèches passent derrière le visage (sous la ligne des sourcils), bord adouci
      lctx.globalCompositeOperation = "destination-out";
      if (feather > 0) lctx.filter = `blur(${feather}px)`;
      lctx.beginPath();
      occlusion.forEach((p, i) => (i ? lctx.lineTo(p.x, p.y) : lctx.moveTo(p.x, p.y)));
      lctx.closePath();
      lctx.fill();
      lctx.filter = "none";
      lctx.globalCompositeOperation = "source-over";
    }
    ctx.globalAlpha = opacity;
    ctx.drawImage(this.layer, 0, 0);
    ctx.globalAlpha = 1;
  }

  dispose() {
    this.layer.width = this.layer.height = 0;
  }
}
