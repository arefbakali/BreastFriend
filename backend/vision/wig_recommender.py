"""Recommandation de perruques par vision par ordinateur (OpenCV, 100 % local).

Pipeline :
 1. Détection du visage (cascade de Haar) et des yeux (points d'ancrage).
 2. Échantillonnage de la peau sur les joues -> espace CIE L*a*b* :
      * profondeur du teint via l'angle ITA (Individual Typology Angle) ;
      * sous-ton chaud / froid / neutre via l'angle de teinte h = atan2(b*, a*).
 3. Segmentation de la peau (distance de Mahalanobis en Cr/Cb autour du
    modèle de peau appris sur les joues) -> largeurs du front, des pommettes
    et de la mâchoire, longueur du visage -> forme du visage.
 4. Score de chaque perruque du catalogue (forme, couleur, teint, longueur,
    confort pendant la chimiothérapie, budget) avec justification lisible.
Les mesures sont des estimations : l'utilisatrice peut corriger la forme.
"""
import base64
import json
import math
from pathlib import Path

import cv2
import numpy as np

CATALOG_PATH = Path(__file__).with_name("wigs_catalog.json")
_FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
_FACE_ALT = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
_EYES = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml")
_EYES_ALT = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")

FACE_SHAPES = {
    "ovale": "Ovale",
    "rond": "Rond",
    "carre": "Carré",
    "coeur": "En cœur",
    "allonge": "Allongé",
}
FACE_TIPS = {
    "ovale": "Votre visage est équilibré : presque toutes les coupes vous vont, vous pouvez vous faire plaisir.",
    "rond": "Les longueurs qui dépassent le menton, une raie sur le côté et du volume sur le dessus allongent visuellement le visage.",
    "carre": "Les dégradés, les ondulations et les longueurs mi-longues adoucissent la ligne de la mâchoire.",
    "coeur": "Un carré mi-long avec du volume au niveau du menton et une frange légère équilibrent le front.",
    "allonge": "Une frange et du volume sur les côtés, en court ou mi-long, équilibrent la longueur du visage.",
}
SKIN_LABELS = [(55, "très clair"), (41, "clair"), (28, "intermédiaire"), (10, "mat"), (-30, "brun"), (-999, "foncé")]
UNDERTONE_LABELS = {"warm": "chaud (doré, pêche)", "cool": "froid (rosé)", "neutral": "neutre"}
LENGTH_ORDER = ["court", "mi-long", "long"]


class FaceNotFound(ValueError):
    pass


def load_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _decode(image_bytes):
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Image illisible : utilisez un fichier JPG ou PNG.")
    h, w = img.shape[:2]
    scale = 900 / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _detect_face(gray):
    h, w = gray.shape
    min_side = int(min(h, w) * 0.12)
    eq = cv2.equalizeHist(gray)
    for cascade, neighbors in ((_FACE, 6), (_FACE_ALT, 4), (_FACE, 3)):
        faces = cascade.detectMultiScale(eq, scaleFactor=1.08, minNeighbors=neighbors, minSize=(min_side, min_side))
        if len(faces):
            return max(faces, key=lambda f: f[2] * f[3]), len(faces)
    raise FaceNotFound("Aucun visage détecté. Prenez une photo de face, bien éclairée, visage dégagé.")


def _detect_eyes(gray, face):
    x, y, w, h = face
    y0 = y + int(h * 0.18)
    roi = cv2.equalizeHist(gray[y0: y + int(h * 0.58), x: x + w])
    min_eye = max(6, int(w * 0.09))
    for cascade, neighbors in ((_EYES, 6), (_EYES_ALT, 5), (_EYES, 3), (_EYES_ALT, 3)):
        found = cascade.detectMultiScale(roi, scaleFactor=1.05, minNeighbors=neighbors, minSize=(min_eye, min_eye),
                                         maxSize=(int(w * 0.35), int(w * 0.35)))
        left = [e for e in found if e[0] + e[2] / 2 < w * 0.5]
        right = [e for e in found if e[0] + e[2] / 2 >= w * 0.5]
        if left and right:
            pick = [max(left, key=lambda e: e[2] * e[3]), max(right, key=lambda e: e[2] * e[3])]
            centers = [(x + ex + ew / 2, y0 + ey + eh / 2) for ex, ey, ew, eh in pick]
            if abs(centers[0][1] - centers[1][1]) < h * 0.12 and centers[1][0] - centers[0][0] > w * 0.22:
                return centers
    return None


def _skin_sample(img, face, eye_y):
    x, y, w, h = face
    top = int(max(eye_y + h * 0.12, y + h * 0.5))
    bot = int(min(top + h * 0.16, y + h * 0.8))
    patches = [img[top:bot, x + int(w * 0.17): x + int(w * 0.34)],
               img[top:bot, x + int(w * 0.66): x + int(w * 0.83)]]
    pixels = np.concatenate([p.reshape(-1, 3) for p in patches if p.size], axis=0)
    if len(pixels) < 20:
        raise FaceNotFound("Visage trop petit dans l'image : rapprochez-vous de l'appareil.")
    # on écarte les reflets et les ombres (10 % extrêmes de luminance)
    lum = pixels.mean(axis=1)
    lo, hi = np.percentile(lum, [10, 90])
    return pixels[(lum >= lo) & (lum <= hi)]


def _skin_tone(pixels_bgr):
    lab = cv2.cvtColor(pixels_bgr.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(float)
    L = np.median(lab[:, 0]) * 100 / 255
    a = np.median(lab[:, 1]) - 128
    b = np.median(lab[:, 2]) - 128
    ita = math.degrees(math.atan2(L - 50, b if abs(b) > 1e-3 else 1e-3))
    depth = next(label for threshold, label in SKIN_LABELS if ita > threshold)
    hue = math.degrees(math.atan2(b, a))
    undertone = "warm" if hue >= 60 else "cool" if hue <= 47 else "neutral"
    rgb = np.median(pixels_bgr, axis=0)[::-1]
    return {
        "L": round(L, 1), "a": round(a, 1), "b": round(b, 1), "ita": round(ita, 1), "hue": round(hue, 1),
        "depth": depth, "undertone": undertone, "undertone_label": UNDERTONE_LABELS[undertone],
        "hex": "#%02x%02x%02x" % tuple(int(v) for v in rgb),
    }


def _skin_mask(img, face, sample):
    x, y, w, h = face
    H, W = img.shape[:2]
    x0, x1 = max(0, x - int(w * 0.25)), min(W, x + w + int(w * 0.25))
    y0, y1 = max(0, y - int(h * 0.3)), min(H, y + h + int(h * 0.35))
    region = img[y0:y1, x0:x1]
    ycc = cv2.cvtColor(region, cv2.COLOR_BGR2YCrCb).reshape(-1, 3).astype(float)
    samp = cv2.cvtColor(sample.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2YCrCb).reshape(-1, 3).astype(float)
    mu = samp[:, 1:].mean(axis=0)
    cov = np.cov(samp[:, 1:].T) + np.eye(2) * 4.0
    inv = np.linalg.inv(cov)
    d = ycc[:, 1:] - mu
    maha = np.einsum("ij,jk,ik->i", d, inv, d)
    y_lo = np.percentile(samp[:, 0], 2) * 0.55
    mask = ((maha < 10.0) & (ycc[:, 0] > y_lo)).reshape(region.shape[:2]).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    # composante connexe contenant le centre du visage
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    cx, cy = x + w // 2 - x0, y + int(h * 0.6) - y0
    lab_id = labels[min(cy, labels.shape[0] - 1), min(cx, labels.shape[1] - 1)]
    if lab_id == 0 and n > 1:
        lab_id = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = np.where(labels == lab_id, 255, 0).astype(np.uint8)
    # bouche, yeux, sourcils ne sont pas « peau » : on remplit les trous du contour
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled, (x0, y0)


def _row_width(mask, row, center_x, max_half):
    """Largeur de peau contiguë autour de l'axe du visage sur une ligne."""
    row = int(np.clip(row, 0, mask.shape[0] - 1))
    line = mask[row] > 0
    c = int(np.clip(center_x, 0, len(line) - 1))
    if not line[c]:
        near = np.where(line)[0]
        if not len(near):
            return 0, c, c
        c = int(near[np.argmin(np.abs(near - c))])
    left = c
    while left > 0 and line[left - 1] and c - left < max_half:
        left -= 1
    right = c
    while right < len(line) - 1 and line[right + 1] and right - c < max_half:
        right += 1
    return right - left, left, right


def _face_shape(mask, offset, face, eyes):
    x, y, w, h = face
    ox, oy = offset
    cx = (np.mean([e[0] for e in eyes]) if eyes else x + w / 2) - ox
    eye_y = (np.mean([e[1] for e in eyes]) if eyes else y + h * 0.4) - oy
    max_half = int(w * 0.75)
    forehead_row = eye_y - h * 0.2
    cheek_row = eye_y + h * 0.15
    jaw_row = eye_y + h * 0.40
    fw, fl, fr = _row_width(mask, forehead_row, cx, max_half)
    cw, cl, cr = _row_width(mask, cheek_row, cx, max_half)
    jw, jl, jr = _row_width(mask, jaw_row, cx, max_half)

    # menton : là où la largeur chute nettement sous la mâchoire
    chin_row = y + h - oy
    for r in range(int(jaw_row), min(mask.shape[0] - 1, int(y + h * 1.35 - oy))):
        width, _, _ = _row_width(mask, r, cx, max_half)
        if width < max(jw, 1) * 0.55:
            chin_row = r
            break
    # haut du visage : ligne des cheveux (ou haut du crâne) dans l'axe du visage
    col = mask[:, int(np.clip(cx, 0, mask.shape[1] - 1))] > 0
    top_row = int(eye_y)
    while top_row > 0 and col[top_row - 1] and eye_y - top_row < h * 0.9:
        top_row -= 1
    length = max(chin_row - top_row, 1)
    ref = max(cw, fw, 1)
    ratios = {"length_width": round(length / ref, 2), "jaw_cheek": round(jw / max(cw, 1), 2),
              "forehead_cheek": round(fw / max(cw, 1), 2)}

    lw, jc, fc = ratios["length_width"], ratios["jaw_cheek"], ratios["forehead_cheek"]
    if lw >= 1.55:
        shape = "allonge"
    elif fc >= 1.0 and jc <= 0.78:
        shape = "coeur"
    elif jc >= 0.9 and lw <= 1.4:
        shape = "carre"
    elif lw <= 1.25 and jc < 0.9:
        shape = "rond"
    else:
        shape = "ovale"

    confidence = 0.55 + (0.2 if eyes else 0) + (0.15 if 0.5 < jc < 1.1 and 0.6 < fc < 1.3 else 0)
    geometry = {
        "forehead": [fl + ox, int(forehead_row + oy), fr + ox],
        "cheek": [cl + ox, int(cheek_row + oy), cr + ox],
        "jaw": [jl + ox, int(jaw_row + oy), jr + ox],
        "top": [int(cx + ox), int(top_row + oy)], "chin": [int(cx + ox), int(chin_row + oy)],
    }
    return shape, round(min(confidence, 0.9), 2), ratios, geometry


def _annotate(img, face, eyes, geo, skin_hex):
    out = img.copy()
    x, y, w, h = face
    pink = (107, 19, 214)
    cv2.rectangle(out, (x, y), (x + w, y + h), (255, 255, 255), 2)
    for key, color in (("forehead", (230, 170, 250)), ("cheek", pink), ("jaw", (140, 60, 190))):
        x0, row, x1 = geo[key]
        cv2.line(out, (x0, row), (x1, row), color, 3)
        cv2.circle(out, (x0, row), 4, color, -1)
        cv2.circle(out, (x1, row), 4, color, -1)
    cv2.line(out, tuple(geo["top"]), tuple(geo["chin"]), (255, 255, 255), 1, cv2.LINE_AA)
    for ex, ey in eyes or []:
        cv2.circle(out, (int(ex), int(ey)), 5, (255, 255, 255), 2)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()


def analyze_face(image_bytes):
    img = _decode(image_bytes)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    face, n_faces = _detect_face(gray)
    x, y, w, h = [int(v) for v in face]
    face = (x, y, w, h)
    eyes = _detect_eyes(gray, face)
    eye_y = np.mean([e[1] for e in eyes]) if eyes else y + h * 0.4
    sample = _skin_sample(img, face, eye_y)
    skin = _skin_tone(sample)
    mask, offset = _skin_mask(img, face, sample)
    shape, confidence, ratios, geo = _face_shape(mask, offset, face, eyes)

    roi = gray[y: y + h, x: x + w]
    warnings = []
    brightness = float(roi.mean())
    sharpness = float(cv2.Laplacian(roi, cv2.CV_64F).var())
    if brightness < 70:
        warnings.append("Photo sombre : l'estimation du teint peut être faussée.")
    if brightness > 215:
        warnings.append("Photo surexposée : l'estimation du teint peut être faussée.")
    if sharpness < 30:
        warnings.append("Photo floue : les mesures du visage sont moins précises.")
    if n_faces > 1:
        warnings.append("Plusieurs visages détectés : le plus grand a été analysé.")
    if not eyes:
        warnings.append("Yeux non détectés (lunettes, cheveux ?) : forme du visage estimée avec moins de précision.")
        confidence = round(confidence - 0.1, 2)

    return {
        "face_box": list(face),
        "eyes_detected": bool(eyes),
        "face_shape": shape,
        "face_shape_label": FACE_SHAPES[shape],
        "face_shape_tip": FACE_TIPS[shape],
        "confidence": confidence,
        "ratios": ratios,
        "skin": skin,
        "quality": {"brightness": round(brightness, 1), "sharpness": round(sharpness, 1)},
        "warnings": warnings,
        "annotated_image": _annotate(img, face, eyes, geo, skin["hex"]),
    }


def recommend(analysis, prefs=None, catalog=None, limit=6):
    prefs = prefs or {}
    catalog = catalog or load_catalog()
    shape = prefs.get("face_shape_override") or analysis["face_shape"]
    undertone = analysis["skin"]["undertone"]
    depth = analysis["skin"]["depth"]
    families = set(prefs.get("color_families") or [])
    length = prefs.get("length")
    texture = prefs.get("texture")
    budget = prefs.get("budget")
    material = prefs.get("material")
    fringe = prefs.get("fringe")  # True / False / None

    results = []
    for wig in catalog:
        score, reasons, cautions = 0, [], []
        if shape == "ovale" or shape in wig["face_shapes"]:
            score += 30
            reasons.append(f"Coupe adaptée à un visage {FACE_SHAPES[shape].lower()}.")
        else:
            score += 8
        if families:
            if wig["color_family"] in families:
                score += 25
                reasons.append(f"Correspond à la couleur choisie ({wig['color_name'].lower()}).")
        else:
            score += 10
        if wig["tone"] == undertone:
            score += 15
            reasons.append(f"Reflets {'chauds' if undertone == 'warm' else 'froids' if undertone == 'cool' else 'neutres'} "
                           f"en harmonie avec votre sous-ton de peau.")
        elif wig["tone"] == "neutral" or undertone == "neutral":
            score += 10
        else:
            score += 3
        if depth in ("brun", "foncé", "mat") and wig["color_family"] in ("noir", "brun"):
            score += 4
        if length:
            dist = abs(LENGTH_ORDER.index(wig["length"]) - LENGTH_ORDER.index(length)) if length in LENGTH_ORDER else 0
            score += {0: 20, 1: 8}.get(dist, 0)
            if dist == 0:
                reasons.append(f"Longueur souhaitée ({wig['length']}).")
        else:
            score += 10
        if texture and wig["texture"] == texture:
            score += 6
        if material and wig["material"] == material:
            score += 5
        if fringe is not None and bool(wig["fringe"]) == bool(fringe):
            score += 4
        if wig["cap"] in ("monofilament", "lace front"):
            score += 4
            reasons.append(f"Bonnet {wig['cap']} : doux pour un cuir chevelu sensible.")
        if wig["weight_g"] <= 110:
            score += 3
            reasons.append(f"Légère ({wig['weight_g']} g), confortable toute la journée.")
        if budget:
            try:
                if wig["price_tnd"] > float(budget):
                    score -= 30
                    cautions.append(f"Au-dessus de votre budget ({wig['price_tnd']} DT).")
            except (TypeError, ValueError):
                pass
        results.append(dict(wig, score=max(0, min(100, score)), reasons=reasons[:4], cautions=cautions))

    results.sort(key=lambda r: (-r["score"], r["price_tnd"]))
    return {"face_shape_used": shape, "face_shape_label": FACE_SHAPES[shape], "tip": FACE_TIPS[shape],
            "items": results[:limit]}
