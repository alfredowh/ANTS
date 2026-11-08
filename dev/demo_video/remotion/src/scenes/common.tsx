import React from "react";

export const BLUE = "#0064E0";
export const INK = "#1c2b33";
export const MUTED = "#5b6b78";
export const GREEN = "#1a9e5a";
export const RED = "#d93a3a";
export const FONT = "Inter, 'Helvetica Neue', Arial, system-ui, sans-serif";

const LOGO_PATH =
  "M12 0h.86v.86H12zM11 1h.86v.86H11zM1 2h.86v.86H1zM2 2h.86v.86H2zM3 2h.86v.86H3zM10 2h.86v.86H10zM11 2h.86v.86H11zM12 2h.86v.86H12zM0 3h.86v.86H0zM1 3h.86v.86H1zM2 3h.86v.86H2zM3 3h.86v.86H3zM4 3h.86v.86H4zM6 3h.86v.86H6zM7 3h.86v.86H7zM8 3h.86v.86H8zM10 3h.86v.86H10zM11 3h.86v.86H11zM12 3h.86v.86H12zM13 3h.86v.86H13zM0 4h.86v.86H0zM1 4h.86v.86H1zM2 4h.86v.86H2zM3 4h.86v.86H3zM4 4h.86v.86H4zM6 4h.86v.86H6zM7 4h.86v.86H7zM8 4h.86v.86H8zM10 4h.86v.86H10zM11 4h.86v.86H11zM12 4h.86v.86H12zM1 5h.86v.86H1zM2 5h.86v.86H2zM3 5h.86v.86H3zM5 5h.86v.86H5zM7 5h.86v.86H7zM9 5h.86v.86H9zM4 6h.86v.86H4zM7 6h.86v.86H7zM10 6h.86v.86H10zM3 7h.86v.86H3zM7 7h.86v.86H7zM11 7h.86v.86H11z";

/** The ants pixel logo from the Studio header, recolored. */
export const Logo: React.FC<{width: number; color?: string; style?: React.CSSProperties}> = ({width, color = BLUE, style}) => (
  <svg width={width} height={(width * 8) / 14} viewBox="0 0 14 8" shape-rendering="crispEdges" style={style}>
    <path d={LOGO_PATH} fill={color} />
  </svg>
);
