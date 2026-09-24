"""Contrôle des calques d'essayage virtuel (spécification : docs/WIG_ASSETS.md).

Un calque utilisable est une image PNG/WebP avec canal alpha, fond transparent (pas de
photo produit sur fond blanc ni de mannequin) et des métadonnées d'ancrage cohérentes.
Les calques refusés sont signalés et l'essayage n'est pas proposé pour cette perruque :
on ne superpose jamais une image rectangulaire sur le visage.
"""
import json
import threading
from pathlib import Path

from PIL import Image

MIN_SIDE = 512
_lock = threading.Lock()
_cache = {}


def validate(static_dir, meta):
    """-> (statut, problèmes)  statut : ok | missing | invalid | unsupported"""
    if not meta:
        return "missing", ["Aucun calque d'essayage (PNG/WebP transparent) pour cette perruque."]
    if meta.get("type", "2d") != "2d":
        return "unsupported", [f"Calque de type « {meta.get('type')} » : rendu 3D pas encore disponible."]
    src = str(meta.get("src", ""))
    if not src.startswith("/static/"):
        return "invalid", ["Chemin du calque invalide (attendu : /static/...)."]
    path = (Path(static_dir) / src[len("/static/"):]).resolve()
    if Path(static_dir).resolve() not in path.parents or not path.is_file():
        return "missing", [f"Fichier introuvable : {src}"]
    issues = []
    try:
        with Image.open(path) as im:
            if im.format not in ("PNG", "WEBP"):
                issues.append(f"Format {im.format} : utiliser PNG ou WebP avec transparence.")
            if min(im.size) < MIN_SIDE:
                issues.append(f"Résolution trop faible ({im.size[0]}×{im.size[1]}, minimum {MIN_SIDE} px).")
            if "A" not in im.getbands():
                issues.append("Pas de canal alpha : l'image a un fond opaque (photo produit ?) — un détourage est nécessaire.")
            else:
                alpha = im.getchannel("A")
                w, h = im.size
                patch = max(8, min(w, h) // 20)
                corners = [(0, 0), (w - patch, 0), (0, h - patch), (w - patch, h - patch)]
                if any(alpha.crop((x, y, x + patch, y + patch)).getextrema()[1] > 16 for x, y in corners):
                    issues.append("Coins opaques : fond non détouré (mannequin ou décor visible).")
                hist = alpha.histogram()
                transparent = sum(hist[:16]) / (w * h)
                if transparent < 0.25:
                    issues.append("Moins de 25 % de pixels transparents : ouverture du visage absente ?")
    except OSError as exc:
        return "invalid", [f"Image illisible : {exc}"]
    anchor, fw = meta.get("anchor") or {}, meta.get("face_width")
    if not (0.2 <= anchor.get("x", -1) <= 0.8 and 0.05 <= anchor.get("y", -1) <= 0.7):
        issues.append("Point d'ancrage (anchor) absent ou hors de l'image.")
    if not (isinstance(fw, (int, float)) and 0.15 <= fw <= 0.9):
        issues.append("Largeur du visage (face_width) absente ou incohérente.")
    return ("invalid" if issues else "ok"), issues


def catalog_with_tryon(catalog_path, static_dir):
    """Catalogue enrichi du statut d'essayage ; recalculé seulement si un fichier change."""
    catalog_path = Path(catalog_path)
    tryon_dir = Path(static_dir) / "wigs" / "tryon"
    stamp = (catalog_path.stat().st_mtime,
             max((p.stat().st_mtime for p in tryon_dir.glob("*")), default=0) if tryon_dir.exists() else 0)
    with _lock:
        if _cache.get("stamp") == stamp:
            return _cache["items"]
        items = json.loads(catalog_path.read_text(encoding="utf-8"))
        for wig in items:
            status, issues = validate(static_dir, wig.get("tryon"))
            wig["tryon_status"] = status
            wig["tryon_issues"] = issues
            if status != "ok":
                wig.pop("tryon", None)
        _cache.update(stamp=stamp, items=items)
        return items


def report(catalog_path, static_dir):
    """Rapport lisible (python -m vision.wig_assets)."""
    items = catalog_with_tryon(catalog_path, static_dir)
    ok = [w for w in items if w["tryon_status"] == "ok"]
    lines = [f"{len(ok)}/{len(items)} perruques avec un calque d'essayage valide."]
    for w in items:
        quality = (w.get("tryon") or {}).get("quality", "")
        mark = "OK " if w["tryon_status"] == "ok" else "!! "
        lines.append(f"{mark}{w['id']} {w['name']:<28} {w['tryon_status']:<11} {quality}")
        lines += [f"      - {i}" for i in w["tryon_issues"]]
    return "\n".join(lines)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    print(report(here / "wigs_catalog.json", here.parent / "static"))
