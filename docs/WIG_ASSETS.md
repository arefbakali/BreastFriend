# Calques d'essayage virtuel — format attendu

L'essayage superpose un **calque 2D transparent** sur le visage suivi par MediaPipe.
Une photo produit (perruque sur mannequin, fond blanc) **ne peut pas** être superposée :
le validateur la refuse et l'essayage n'est pas proposé pour ce modèle.

## État actuel du catalogue

| Élément | Présent ? |
|---|---|
| Photo produit | **non** (aucune) |
| Calque PNG transparent réel (photo détourée) | **non** |
| Modèle 3D | **non** |
| Calque illustratif généré (`backend/static/wigs/tryon/*.png`) | oui, 24/24 — `quality: "illustrative"` |

Les calques illustratifs sont dessinés à partir des attributs du catalogue (longueur,
texture, frange, couleur). Ils montrent la coupe et la couleur, pas le rendu réel du
produit, et l'interface l'indique. Ils sont régénérables :
`node backend/scripts/generate_wig_overlays.mjs`.

## Spécification d'un calque réel

- **Format** : PNG ou WebP, RGBA (canal alpha obligatoire), 8 bits.
- **Taille** : ≥ 1024 px de large recommandé (minimum 512 px).
- **Prise de vue** : perruque de face, tête droite, éclairage diffus et neutre.
- **Détourage** : fond entièrement transparent (coins alpha = 0) ; **l'ouverture du
  visage doit être transparente** (front sous la frange, yeux, joues, bouche). Bords des
  mèches adoucis (pas de liseré blanc).
- **Mannequin** : aucun pixel du mannequin (peau, yeux) ne doit rester visible.
- **Cadrage** : image entière de la perruque, avec de la marge transparente.

### Métadonnées (dans `backend/vision/wigs_catalog.json`, champ `tryon`)

```json
"tryon": {
  "type": "2d",
  "src": "/static/wigs/tryon/w01.png",
  "width": 1024,
  "height": 1400,
  "anchor": { "x": 0.5, "y": 0.2571 },
  "face_width": 0.42,
  "quality": "photo"
}
```

- `anchor` : point (fractions de largeur / hauteur) qui doit se poser sur **le milieu
  de la ligne frontale** (repère MediaPipe n° 10, haut du front).
- `face_width` : largeur **tempe à tempe** (repères 234 ↔ 454) exprimée en fraction de
  la largeur de l'image. Pour la mesurer : placer l'image sur une photo de face à
  l'échelle réelle et relever la distance entre les bords du visage à hauteur des yeux.
- `quality` : `"photo"` pour un vrai calque, `"illustrative"` sinon (bandeau affiché).

### Vérification

```
cd backend
python -m vision.wig_assets
```

liste chaque perruque avec `ok`, `missing`, `invalid` (et la raison : pas d'alpha, coins
opaques, résolution, métadonnées) ou `unsupported`.

## Évolution vers la 3D

Le moteur de rendu est isolé derrière une interface (`resize`, `draw`, `dispose`) dans
`frontend/src/lib/tryon/renderer2d.js`. Un rendu 3D recevrait la même pose de tête ; il
suffira d'ajouter `type: "3d"` + un fichier glTF/GLB (`src`), une échelle et un décalage
d'ancrage, puis un `renderer3d.js` (three.js) choisi par `TryOn.jsx` selon `type`.
La pose 3D complète (matrice de transformation faciale MediaPipe,
`outputFacialTransformationMatrixes`) devra alors être activée.
