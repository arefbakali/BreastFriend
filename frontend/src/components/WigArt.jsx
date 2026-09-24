import React from "react";

// Silhouette stylisée d'une perruque, colorée selon la teinte et la longueur du modèle.
const HAIR = {
  court: "M60 34c-22 0-36 15-36 36 0 9 2 16 5 21 1-12 6-22 14-27 8 6 22 9 34 8 7 6 10 12 12 19 3-5 7-12 7-22 0-20-14-35-36-35z",
  "mi-long": "M60 30c-24 0-38 17-38 40 0 20 2 33-6 46 10 2 20 0 26-4-5-10-6-22-4-33 9 4 26 5 38 2 3 12 2 24-4 34 7 4 17 5 26 2-7-13-5-28-5-47 0-23-14-40-33-40z",
  long: "M60 28c-25 0-39 18-39 42 0 26 3 44-10 62 14 5 28 3 36-3-6-14-8-32-6-48 9 4 25 5 37 2 3 16 1 33-6 47 9 6 22 7 35 2-12-17-9-37-9-62 0-24-14-42-38-42z",
};

export default function WigArt({ wig, size = 96 }) {
  const curly = wig.texture === "boucle";
  const wavy = wig.texture === "ondule";
  return (
    <svg viewBox="0 0 120 140" width={size} height={size * 1.16} role="img" aria-label={`${wig.style}, ${wig.color_name}`}>
      <ellipse cx="60" cy="72" rx="22" ry="27" fill="#F3D3C4" />
      <path d="M46 96c4 10 24 10 28 0v14H46z" fill="#EFC6B4" />
      <path d={HAIR[wig.length] || HAIR.court} fill={wig.color_hex} stroke="rgba(0,0,0,.18)" strokeWidth="1.2"
        strokeDasharray={curly ? "2 3" : wavy ? "6 3" : "0"} />
      {wig.fringe && <path d="M40 58c8-9 30-11 42-2-6-2-14-2-20 3-6-5-15-4-22-1z" fill={wig.color_hex} opacity=".95" />}
      <path d="M52 82c4 3 12 3 16 0" stroke="#C98E80" strokeWidth="2" fill="none" strokeLinecap="round" />
    </svg>
  );
}
