import React from 'react';

/**
 * The Quancis brand mark: a 4x4 grid of 100x100 cells on a 400x400 canvas.
 *
 *   .xx.
 *   x..x
 *   x.x.
 *   .x.R
 *
 * Cells that are the same color AND share an edge are drawn as one
 * combined <rect> instead of two abutting ones — two adjacent same-color
 * rects can leave a faint anti-aliased seam at the shared border, and
 * every same-color adjacency here happens to already be axis-aligned
 * (a 1x2 or 2x1 block), so a single merged rect is enough; no path
 * boolean-union is needed. The red cell touches no other filled cell,
 * so it stays independent.
 *
 * shape-rendering="crispEdges" turns off anti-aliasing on the rect edges
 * so the grid lines stay sharp at small sizes (e.g. a 32px favicon-ish
 * badge) instead of going soft/blurry.
 */

// `currentColor` for the black cells so the mark can switch to white
// over a dark background (e.g. the header before it scrolls past the
// hero) just by the surrounding text color changing — same mechanism
// the "uancis" wordmark next to it already uses. The red cell is a
// fixed brand color and never changes.
const BLACK = 'currentColor';
const RED = '#E4002B';

// Each shape's stagger delay for the loading animation, in seconds.
// Ordered roughly top-left -> bottom-right so the pulse reads as a
// single diagonal wave rather than a random flicker.
const SHAPES: { d: string; fill: string; delay: number }[] = [
  // (1,0)+(2,0) merged — top bar
  { d: 'M100,0 H300 V100 H100 Z', fill: BLACK, delay: 0 },
  // (0,1)+(0,2) merged — left bar
  { d: 'M0,100 H100 V300 H0 Z', fill: BLACK, delay: 0.08 },
  // (3,1) isolated
  { d: 'M300,100 H400 V200 H300 Z', fill: BLACK, delay: 0.16 },
  // (2,2) isolated
  { d: 'M200,200 H300 V300 H200 Z', fill: BLACK, delay: 0.24 },
  // (1,3) isolated
  { d: 'M100,300 H200 V400 H100 Z', fill: BLACK, delay: 0.32 },
  // (3,3) isolated — red
  { d: 'M300,300 H400 V400 H300 Z', fill: RED, delay: 0.4 },
];

export interface BrandMarkProps {
  /** Rendered width/height in px. The mark is always square. */
  size?: number;
  /** Plays a staggered pulse across the cells — use during async work
   *  (signing in, switching between major tabs) instead of a generic
   *  spinner. */
  animated?: boolean;
  className?: string;
  title?: string;
}

export const BrandMark: React.FC<BrandMarkProps> = ({
  size = 40,
  animated = false,
  className = '',
  title = 'Quancis',
}) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 400 400"
      xmlns="http://www.w3.org/2000/svg"
      shapeRendering="crispEdges"
      className={className}
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      {SHAPES.map((shape, i) => (
        <path
          key={i}
          d={shape.d}
          fill={shape.fill}
          className={animated ? 'animate-brandmark-pulse' : undefined}
          style={animated ? { animationDelay: `${shape.delay}s` } : undefined}
        />
      ))}
    </svg>
  );
};

export default BrandMark;
