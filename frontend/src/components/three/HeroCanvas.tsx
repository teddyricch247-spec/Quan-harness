'use client';

import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

/**
 * The hero background: a rippling field of instanced boxes rendered
 * with Three.js — a rolling wave terrain with occasional red boxes
 * (echoing the brand mark's red cell) and occasional "missing" boxes,
 * lifting further wherever the pointer hovers. Ported 1:1 (constants,
 * shaders, camera behavior included) from the reference design so the
 * motion and tuning match exactly; only the lifecycle wiring (mount/
 * unmount cleanup, resize via ResizeObserver instead of a bare window
 * resize listener) was adapted for React.
 */
export const HeroCanvas: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const heroRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const heroElem = heroRef.current;
    if (!canvas || !heroElem) return;

    let disposed = false;
    let rafId = 0;

    // WebGL isn't guaranteed to exist (headless environments, some
    // locked-down browsers, ancient devices) — the whole hero must not
    // take the page down if it doesn't. On any setup failure, bail out
    // quietly; the hero section's own `bg-hero` background color is
    // already a reasonable dark fallback with no canvas on top of it.
    try {

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const small = Math.min(window.innerWidth, window.innerHeight) < 720;
    const N = small ? 64 : 88;
    const HALF = N / 2;
    const BOX = 0.58;
    const AMP = 2.55;
    const BASE_H = 0.09;
    const FADE_A = HALF * 0.55;
    const FADE_B = HALF * 1.02;

    const RED_CHANCE = 0.021;
    const MISSING_CHANCE = 0.058;

    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    });
    renderer.setClearColor(0x000000, 0);
    renderer.autoClear = false;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.5, 600);

    const uTime = { value: 0 };

    const EDGE_GLSL = `
      float edgeWave(float x, float t) {
        float e = 0.0;
        e += sin(x * 1.70 + t * 0.30) * 0.017;
        e += sin(x * 4.10 - t * 0.46) * 0.0080;
        e += sin(x * 0.90 + t * 0.17) * 0.0130;
        e += sin(x * 8.30 + t * 0.61) * 0.0035;
        return e;
      }
    `;

    const bgScene = new THREE.Scene();
    const bgCamera = new THREE.Camera();

    const EDGE = 0.10;
    const EDGE_SOFT = 0.075;

    const bgUniforms = {
      uTime,
      uAspect: { value: 1.8 },
      uEdge: { value: EDGE },
      uSoft: { value: EDGE_SOFT },
      uBg: { value: new THREE.Vector3(0x1a / 255, 0x1c / 255, 0x1e / 255) },
      uGlow: { value: new THREE.Vector3(0.072, 0.086, 0.106) },
    };

    const bgMaterial = new THREE.ShaderMaterial({
      uniforms: bgUniforms,
      depthTest: false,
      depthWrite: false,
      vertexShader: `
        varying vec2 vUv;
        void main() {
          vUv = uv;
          gl_Position = vec4(position.xy, 0.0, 1.0);
        }
      `,
      fragmentShader: `
        precision highp float;
        uniform float uTime;
        uniform float uAspect;
        uniform float uEdge;
        uniform float uSoft;
        uniform vec3  uBg;
        uniform vec3  uGlow;
        varying vec2 vUv;
        ${EDGE_GLSL}
        void main() {
          float b = uEdge + edgeWave(vUv.x * uAspect, uTime);
          float a = smoothstep(b - uSoft, b + uSoft, vUv.y);
          if (a <= 0.002) discard;
          vec2 g = (vUv - vec2(0.5, 0.66)) / vec2(0.54, 0.38);
          float glow = exp(-dot(g, g) * 2.2);
          vec3 col = uBg + uGlow * glow;
          gl_FragColor = vec4(col, a);
        }
      `,
    });
    const bgGeo = new THREE.PlaneGeometry(2, 2);
    const bgMesh = new THREE.Mesh(bgGeo, bgMaterial);
    bgMesh.frustumCulled = false;
    bgScene.add(bgMesh);

    const base = new THREE.BoxGeometry(1, 1, 1);
    base.translate(0, 0.5, 0);

    const geo = new THREE.InstancedBufferGeometry();
    geo.setIndex(base.index);
    geo.setAttribute('position', base.attributes.position);
    geo.setAttribute('normal', base.attributes.normal);
    geo.instanceCount = N * N;

    const offsets = new Float32Array(N * N * 2);
    const rands = new Float32Array(N * N);
    const reds = new Float32Array(N * N);
    const missing = new Float32Array(N * N);

    let o = 0;
    let i = 0;
    for (let x = 0; x < N; x++) {
      for (let z = 0; z < N; z++) {
        offsets[o] = x - HALF + 0.5;
        offsets[o + 1] = z - HALF + 0.5;
        rands[i] = Math.random();
        const isMissing = Math.random() < MISSING_CHANCE;
        const isRed = !isMissing && Math.random() < RED_CHANCE;
        missing[i] = isMissing ? 1 : 0;
        reds[i] = isRed ? 1 : 0;
        o += 2;
        i += 1;
      }
    }

    geo.setAttribute('aOffset', new THREE.InstancedBufferAttribute(offsets, 2));
    geo.setAttribute('aRand', new THREE.InstancedBufferAttribute(rands, 1));
    geo.setAttribute('aRed', new THREE.InstancedBufferAttribute(reds, 1));
    geo.setAttribute('aMissing', new THREE.InstancedBufferAttribute(missing, 1));

    const v3 = (r: number, g: number, b: number) => new THREE.Vector3(r / 255, g / 255, b / 255);

    const uniforms = {
      uTime,
      uMouse: { value: new THREE.Vector2(0, -200) },
      uMouseStrength: { value: 0 },
      uAmp: { value: AMP },
      uBase: { value: BASE_H },
      uBoxScale: { value: BOX },
      uRes: { value: new THREE.Vector2(1, 1) },
      uAspect: { value: 1.8 },
      uEdge: { value: EDGE },
      uSoft: { value: EDGE_SOFT },
      uColorLow: { value: v3(0x1e, 0x22, 0x27) },
      uColorHigh: { value: v3(0x5e, 0x6b, 0x79) },
      uColorRed: { value: v3(0xd8, 0x3b, 0x32) },
      uFadeStart: { value: FADE_A },
      uFadeEnd: { value: FADE_B },
    };

    const vertexShader = `
      uniform float uTime;
      uniform vec2  uMouse;
      uniform float uMouseStrength;
      uniform float uAmp;
      uniform float uBase;
      uniform float uBoxScale;
      attribute vec2  aOffset;
      attribute float aRand;
      attribute float aRed;
      attribute float aMissing;
      varying float vH;
      varying vec3  vNormalW;
      varying vec3  vWorld;
      varying float vRand;
      varying float vRed;
      varying float vMissing;

      float waveField(vec2 p, float t) {
        float w = 0.0;
        w += sin(p.x * 0.230 + p.y * 0.170 - t * 1.20);
        w += sin(p.x * 0.130 - p.y * 0.235 + t * 0.95) * 0.78;
        w += sin(length(p) * 0.185 - t * 0.80) * 0.62;
        w += sin(p.x * 0.055 + p.y * 0.045 + t * 0.42) * 0.40;
        return w / 2.80;
      }

      void main() {
        vec2 p = aOffset;
        float n = waveField(p, uTime) * 0.5 + 0.5;
        float d    = distance(p, uMouse);
        float infl = exp(-d * d / 22.0);
        n += uMouseStrength * infl * 1.45
             * (1.0 + 0.20 * sin(uTime * 2.4 - d * 0.8));
        n = clamp(n, 0.0, 2.6);
        float h = uBase + n * uAmp;
        h *= 1.0 + aRed * 0.45;
        vec3 pos = position;
        pos.x *= uBoxScale;
        pos.z *= uBoxScale;
        pos.y *= h;
        vWorld   = vec3(p.x + pos.x, pos.y, p.y + pos.z);
        vNormalW = normal;
        vH       = n;
        vRand    = aRand;
        vRed     = aRed;
        vMissing = aMissing;
        gl_Position = projectionMatrix * viewMatrix * vec4(vWorld, 1.0);
      }
    `;

    const fragmentShader = `
      precision highp float;
      uniform vec2  uRes;
      uniform float uAspect;
      uniform float uTime;
      uniform float uEdge;
      uniform float uSoft;
      uniform vec3  uColorLow;
      uniform vec3  uColorHigh;
      uniform vec3  uColorRed;
      uniform float uFadeStart;
      uniform float uFadeEnd;
      varying float vH;
      varying vec3  vNormalW;
      varying vec3  vWorld;
      varying float vRand;
      varying float vRed;
      varying float vMissing;
      ${EDGE_GLSL}

      void main() {
        if (vMissing > 0.5) discard;
        vec3  nrm  = normalize(vNormalW);
        float diff = clamp(dot(nrm, normalize(vec3(0.40, 1.0, 0.55))), 0.0, 1.0);
        vec3 baseCol = mix(uColorLow, uColorHigh, clamp(vH * 0.62, 0.0, 1.0));
        baseCol *= 0.34 + 0.95 * diff;
        vec3 redCol = uColorRed * (0.46 + 0.88 * diff);
        vec3 col = mix(baseCol, redCol, vRed);
        float r  = length(vWorld.xz);
        float rf = 1.0 - smoothstep(uFadeStart, uFadeEnd, r);
        float sx = (gl_FragCoord.x / uRes.x) * uAspect;
        float sy =  gl_FragCoord.y / uRes.y;
        float b = uEdge - 0.035
                + edgeWave(sx, uTime)
                + (vRand - 0.5) * 0.085;
        float a = rf * smoothstep(b - uSoft, b + uSoft, sy);
        if (a <= 0.004) discard;
        gl_FragColor = vec4(col, a);
      }
    `;

    const material = new THREE.ShaderMaterial({
      uniforms,
      vertexShader,
      fragmentShader,
      transparent: true,
      depthWrite: true,
      side: THREE.FrontSide,
    });

    const mesh = new THREE.Mesh(geo, material);
    mesh.frustumCulled = false;
    scene.add(mesh);

    function layout() {
      if (!heroElem) return;
      const w = heroElem.clientWidth;
      const h = heroElem.clientHeight;
      if (!w || !h) return;
      const aspect = w / h;
      camera.aspect = aspect;
      const t = THREE.MathUtils.clamp((1.3 - aspect) / 0.9, 0, 1);
      camera.fov = THREE.MathUtils.lerp(42, 48, t);
      const py = THREE.MathUtils.lerp(16.5, 40, t);
      const pz = THREE.MathUtils.lerp(29, 39, t);
      const tz = THREE.MathUtils.lerp(-6, -7, t);
      camera.position.set(0, py, pz);
      camera.lookAt(0, 0, tz);
      camera.updateProjectionMatrix();

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      renderer.setPixelRatio(dpr);
      renderer.setSize(w, h, false);

      const buf = renderer.getDrawingBufferSize(new THREE.Vector2());
      uniforms.uRes.value.copy(buf);
      uniforms.uAspect.value = buf.x / buf.y;
      bgUniforms.uAspect.value = buf.x / buf.y;
    }

    layout();
    window.addEventListener('resize', layout);
    const onOrientation = () => setTimeout(layout, 120);
    window.addEventListener('orientationchange', onOrientation);

    const raycaster = new THREE.Raycaster();
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const ndc = new THREE.Vector2();
    const hit = new THREE.Vector3();

    const mouseTarget = new THREE.Vector2(0, -200);
    const mouseSmooth = new THREE.Vector2(0, -200);
    let strengthTarget = 0;
    let strength = 0;
    let touchTimer: ReturnType<typeof setTimeout>;

    function scheduleRelease(pointerType: string) {
      if (pointerType === 'mouse') return;
      clearTimeout(touchTimer);
      touchTimer = setTimeout(() => {
        strengthTarget = 0;
      }, 1200);
    }

    // Pointer tracking lives on `window`, NOT on the canvas or its wrapper.
    //
    // The canvas sits BEHIND the hero content (-z-10). Anything drawn over
    // it (headline, paragraph, buttons, the fixed nav) is what the browser
    // actually hits, and events that land on those elements are not
    // descendants of the canvas wrapper, so they never reach a listener
    // attached there. That was the old bug: the boxes only reacted where
    // the pointer happened to be over bare background.
    //
    // Window-level listeners see every pointer event wherever it lands; we
    // then decide "is the pointer over the hero?" with a bounds check
    // against the canvas rect (identical to the hero section's box) instead
    // of relying on which element was hit. The listeners are passive and
    // never call preventDefault, so text selection, clicks, and page
    // scrolling behave exactly as before. On touch, the browser may take
    // over a vertical drag for scrolling (pointercancel); that is the
    // desired trade-off, since the hero is a full screen tall and must stay
    // scrollable. Taps and the start of a drag still register.
    const track = (e: PointerEvent) => {
      const r = canvas.getBoundingClientRect();
      const inside =
        e.clientX >= r.left && e.clientX <= r.right &&
        e.clientY >= r.top && e.clientY <= r.bottom;
      if (!inside) {
        // A mouse that has left the hero stops lifting boxes at once.
        // Touch/pen keep the short release timer instead.
        if (e.pointerType === 'mouse') strengthTarget = 0;
        return;
      }
      ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      raycaster.setFromCamera(ndc, camera);
      if (raycaster.ray.intersectPlane(plane, hit)) {
        mouseTarget.set(hit.x, hit.z);
      }
      strengthTarget = 1;
      scheduleRelease(e.pointerType);
    };

    const onPointerMove = (e: PointerEvent) => track(e);
    const onPointerDown = (e: PointerEvent) => track(e);

    // Finger lifted, or the browser took the gesture over to scroll the page:
    // let go AT ONCE. This is how the animation always behaved — on touch the
    // hero's `pointerleave` fired right after `pointerup` and zeroed the lift
    // immediately — so a quick tap only nudges the boxes and they settle in
    // about half a second. Waiting for the release timer here instead makes
    // every tap shoot to full height and hang there for over a second (the
    // regression this replaces). Pen keeps the timer, as before; the timer
    // also stays as a safety net if a touch's pointerup is ever lost.
    const onPointerRelease = (e: PointerEvent) => {
      if (e.pointerType === 'touch') {
        clearTimeout(touchTimer);
        strengthTarget = 0;
      } else {
        scheduleRelease(e.pointerType);
      }
    };
    const onPointerUp = onPointerRelease;
    const onPointerCancel = onPointerRelease;
    // Mouse left the browser window entirely (no further moves will say so).
    // Mouse only: a touch pointer "leaves" when the finger lifts, and
    // onPointerRelease already handles that.
    const onDocLeave = (e: PointerEvent) => {
      if (e.pointerType === 'mouse') strengthTarget = 0;
    };
    const onWindowBlur = () => {
      strengthTarget = 0;
    };

    window.addEventListener('pointermove', onPointerMove, { passive: true });
    window.addEventListener('pointerdown', onPointerDown, { passive: true });
    window.addEventListener('pointerup', onPointerUp, { passive: true });
    window.addEventListener('pointercancel', onPointerCancel, { passive: true });
    document.documentElement.addEventListener('pointerleave', onDocLeave);
    window.addEventListener('blur', onWindowBlur);

    let visible = true;
    let observer: IntersectionObserver | null = null;
    if ('IntersectionObserver' in window) {
      observer = new IntersectionObserver(
        ([entry]) => {
          visible = entry.isIntersecting;
        },
        { threshold: 0 }
      );
      observer.observe(heroElem);
    }

    let last = performance.now();
    let clock = 0;

    function frame(now: number) {
      rafId = requestAnimationFrame(frame);
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      if (!visible || disposed) return;
      if (!reduceMotion) clock += dt;

      const kPos = 1 - Math.pow(0.0008, dt);
      const kStr = 1 - Math.pow(0.02, dt);

      mouseSmooth.lerp(mouseTarget, kPos);
      strength += (strengthTarget - strength) * kStr;

      uTime.value = clock;
      uniforms.uMouse.value.copy(mouseSmooth);
      uniforms.uMouseStrength.value = strength;

      renderer.clear();
      renderer.render(bgScene, bgCamera);
      renderer.render(scene, camera);
    }

    rafId = requestAnimationFrame(frame);

    return () => {
      disposed = true;
      cancelAnimationFrame(rafId);
      clearTimeout(touchTimer);
      window.removeEventListener('resize', layout);
      window.removeEventListener('orientationchange', onOrientation);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointercancel', onPointerCancel);
      document.documentElement.removeEventListener('pointerleave', onDocLeave);
      window.removeEventListener('blur', onWindowBlur);
      observer?.disconnect();
      geo.dispose();
      base.dispose();
      bgGeo.dispose();
      material.dispose();
      bgMaterial.dispose();
      renderer.dispose();
    };

    } catch (err) {
      console.warn('HeroCanvas: WebGL setup failed, falling back to the flat hero background.', err);
      return;
    }
  }, []);

  return (
    <div ref={heroRef} className="absolute inset-0 -z-10">
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full block" />
    </div>
  );
};

export default HeroCanvas;
