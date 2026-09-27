(() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  function __accessProp(key) {
    return this[key];
  }
  var __toCommonJS = (from) => {
    var entry = (__moduleCache ??= new WeakMap).get(from), desc;
    if (entry)
      return entry;
    entry = __defProp({}, "__esModule", { value: true });
    if (from && typeof from === "object" || typeof from === "function") {
      for (var key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(entry, key))
          __defProp(entry, key, {
            get: __accessProp.bind(from, key),
            enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable
          });
    }
    __moduleCache.set(from, entry);
    return entry;
  };
  var __moduleCache;

  // src/ghost-cursor-client.ts
  var exports_ghost_cursor_client = {};

  // src/assets/cursors/screen-studio/pointer-macos-tahoe-svg.ts
  var SCREENSTUDIO_POINTER_MACOS_TAHOE_SVG = `<svg width="618" height="958" viewBox="0 0 618 958" fill="none" xmlns="http://www.w3.org/2000/svg">
<g filter="url(#filter0_d_384_27)">
<path fill-rule="evenodd" clip-rule="evenodd" d="M127.062 37.0331L540.696 451.555C592.653 503.66 555.794 592.574 482.226 592.574L421.831 592.569L481.821 735.054C492.331 760.021 492.479 787.652 482.265 812.767C472.002 837.932 452.561 857.57 427.496 868.08C414.864 873.359 401.64 876.024 388.121 876.024C347.117 876.024 310.358 851.6 294.47 813.804L231.42 663.918L190.368 700.337C137.029 747.508 53 709.663 53 638.413V67.6744C53 28.9903 99.7268 9.64828 127.062 37.0331Z" fill="white"/>
<path fill-rule="evenodd" clip-rule="evenodd" d="M102.316 99.652C102.316 93.1882 110.162 89.9316 114.701 94.5204L504.897 485.555C526.164 506.871 511.065 543.236 480.967 543.236L347.546 543.161L436.342 754.143C447.542 780.788 435.009 811.429 408.414 822.581C381.72 833.781 351.128 821.298 339.977 794.702L250.293 581.352L158.517 662.644C137.991 680.801 106.319 668.145 102.664 642.323L102.316 637.331V99.652Z" fill="black"/>
</g>
<defs>
<filter id="filter0_d_384_27" x="0.34" y="0.799219" width="617.32" height="957.144" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB">
<feFlood flood-opacity="0" result="BackgroundImageFix"/>
<feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha"/>
<feOffset dy="29.26"/>
<feGaussianBlur stdDeviation="26.33"/>
<feComposite in2="hardAlpha" operator="out"/>
<feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.65 0"/>
<feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow_384_27"/>
<feBlend mode="normal" in="SourceGraphic" in2="effect1_dropShadow_384_27" result="shape"/>
</filter>
</defs>
</svg>`;

  // src/ghost-cursor-client.ts
  var isTopFrame = (() => {
    try {
      return window === window.top;
    } catch {
      return false;
    }
  })();
  var CURSOR_ID = "__playwriter_ghost_cursor__";
  var SCREENSTUDIO_POINTER_ASPECT_RATIO = 618 / 958;
  var SCREENSTUDIO_HOTSPOT_X_RATIO = 0.14;
  var SCREENSTUDIO_HOTSPOT_Y_RATIO = 0.06;
  var MINIMAL_TRIANGLE_HOTSPOT_X_RATIO = 0.07;
  var MINIMAL_TRIANGLE_HOTSPOT_Y_RATIO = 0.06;
  var MOVE_EASING = "cubic-bezier(0.65, 0, 0.35, 1)";
  var PRESS_EASING = "cubic-bezier(0.23, 1, 0.32, 1)";
  var PRESS_DURATION_MS = 140;
  var IDLE_HIDE_DELAY_MS = 5000;
  var IDLE_FADE_OUT_MS = 600;
  var DEFAULT_OPTIONS = {
    style: "minimal",
    color: "#111827",
    size: 22,
    zIndex: 2147483647,
    easing: MOVE_EASING,
    minDurationMs: 220,
    maxDurationMs: 1500,
    speedPxPerMs: 1.2
  };
  var runtime = {
    outerElement: null,
    innerElement: null,
    options: DEFAULT_OPTIONS,
    x: 0,
    y: 0,
    scale: 1,
    hasPosition: false,
    enabled: false,
    idleHidden: false
  };
  var idleHideTimer = null;
  function clamp(options) {
    const { value, min, max } = options;
    return Math.min(max, Math.max(min, value));
  }
  function mergeOptions(options) {
    if (!options) {
      return DEFAULT_OPTIONS;
    }
    return {
      style: options.style ?? DEFAULT_OPTIONS.style,
      color: options.color ?? DEFAULT_OPTIONS.color,
      size: options.size ?? DEFAULT_OPTIONS.size,
      zIndex: options.zIndex ?? DEFAULT_OPTIONS.zIndex,
      easing: options.easing ?? DEFAULT_OPTIONS.easing,
      minDurationMs: options.minDurationMs ?? DEFAULT_OPTIONS.minDurationMs,
      maxDurationMs: options.maxDurationMs ?? DEFAULT_OPTIONS.maxDurationMs,
      speedPxPerMs: options.speedPxPerMs ?? DEFAULT_OPTIONS.speedPxPerMs
    };
  }
  function getCursorDimensions() {
    if (runtime.options.style === "screenstudio") {
      const height = runtime.options.size;
      const width = Math.max(10, Math.round(height * SCREENSTUDIO_POINTER_ASPECT_RATIO));
      return { width, height };
    }
    if (runtime.options.style === "minimal") {
      const size = Math.max(12, runtime.options.size);
      return { width: size, height: size };
    }
    return { width: runtime.options.size, height: runtime.options.size };
  }
  function getHotspotOffsetPx() {
    const dimensions = getCursorDimensions();
    if (runtime.options.style === "screenstudio") {
      return {
        x: Math.round(dimensions.width * SCREENSTUDIO_HOTSPOT_X_RATIO),
        y: Math.round(dimensions.height * SCREENSTUDIO_HOTSPOT_Y_RATIO)
      };
    }
    if (runtime.options.style === "minimal") {
      return {
        x: Math.round(dimensions.width * MINIMAL_TRIANGLE_HOTSPOT_X_RATIO),
        y: Math.round(dimensions.height * MINIMAL_TRIANGLE_HOTSPOT_Y_RATIO)
      };
    }
    return {
      x: Math.round(dimensions.width / 2),
      y: Math.round(dimensions.height / 2)
    };
  }
  function getBaseOpacity() {
    if (runtime.options.style === "screenstudio") {
      return "0.95";
    }
    if (runtime.options.style === "minimal") {
      return "1";
    }
    return "0.72";
  }
  function applyTranslate() {
    if (!runtime.outerElement) {
      return;
    }
    const hotspot = getHotspotOffsetPx();
    runtime.outerElement.style.transform = `translate3d(${runtime.x - hotspot.x}px, ${runtime.y - hotspot.y}px, 0)`;
  }
  function applyScale() {
    if (!runtime.innerElement) {
      return;
    }
    runtime.innerElement.style.transform = `scale(${runtime.scale})`;
  }
  function computeDurationMs(options) {
    if (!runtime.hasPosition) {
      return 0;
    }
    const dx = options.targetX - runtime.x;
    const dy = options.targetY - runtime.y;
    const distance = Math.hypot(dx, dy);
    const rawDurationMs = distance / runtime.options.speedPxPerMs;
    return clamp({
      value: rawDurationMs,
      min: runtime.options.minDurationMs,
      max: runtime.options.maxDurationMs
    });
  }
  function createCursorElement() {
    const outer = document.createElement("div");
    outer.id = CURSOR_ID;
    outer.setAttribute("aria-hidden", "true");
    outer.style.position = "fixed";
    outer.style.left = "0";
    outer.style.top = "0";
    outer.style.pointerEvents = "none";
    outer.style.zIndex = `${runtime.options.zIndex}`;
    outer.style.transitionProperty = "transform";
    outer.style.transitionTimingFunction = runtime.options.easing;
    outer.style.transitionDuration = "0ms";
    outer.style.willChange = "transform";
    const inner = document.createElement("div");
    inner.style.transitionProperty = "transform, opacity";
    inner.style.transitionTimingFunction = PRESS_EASING;
    inner.style.transitionDuration = `${PRESS_DURATION_MS}ms`;
    inner.style.opacity = getBaseOpacity();
    outer.appendChild(inner);
    runtime.outerElement = outer;
    runtime.innerElement = inner;
    applyRuntimeVisualOptions();
    return outer;
  }
  function ensureCursorElement() {
    const existing = document.getElementById(CURSOR_ID);
    if (existing) {
      runtime.outerElement = existing;
      runtime.innerElement = existing.firstElementChild || null;
      return existing;
    }
    const outer = createCursorElement();
    const root = document.documentElement || document.body;
    root.appendChild(outer);
    return outer;
  }
  function applyRuntimeVisualOptions() {
    if (!runtime.innerElement) {
      return;
    }
    const dimensions = getCursorDimensions();
    runtime.innerElement.style.width = `${dimensions.width}px`;
    runtime.innerElement.style.height = `${dimensions.height}px`;
    if (runtime.outerElement) {
      runtime.outerElement.style.zIndex = `${runtime.options.zIndex}`;
      runtime.outerElement.style.transitionTimingFunction = runtime.options.easing;
    }
    const hotspot = getHotspotOffsetPx();
    runtime.innerElement.style.transformOrigin = `${hotspot.x}px ${hotspot.y}px`;
    runtime.innerElement.replaceChildren();
    runtime.innerElement.style.backgroundImage = "none";
    if (runtime.options.style === "screenstudio") {
      runtime.innerElement.style.borderRadius = "0";
      runtime.innerElement.style.border = "none";
      runtime.innerElement.style.backgroundColor = "transparent";
      runtime.innerElement.style.backdropFilter = "none";
      runtime.innerElement.style.filter = "none";
      runtime.innerElement.style.boxShadow = "none";
      runtime.innerElement.style.opacity = getBaseOpacity();
      setInnerSvg(runtime.innerElement, SCREENSTUDIO_POINTER_MACOS_TAHOE_SVG);
      return;
    }
    if (runtime.options.style === "minimal") {
      const triangleSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="-1 -1 26 26"><path fill="white" stroke="${runtime.options.color}" stroke-width="1.5" stroke-linejoin="round" d="m23.284 19.124l-6.866-6.895a.4.4 0 0 1-.118-.296a.43.43 0 0 1 .163-.282l4.439-3.077a1.48 1.48 0 0 0 .621-1.48a1.48 1.48 0 0 0-1.036-1.198L1.623.302a1.14 1.14 0 0 0-1.11.282A1.13 1.13 0 0 0 .29 1.649L5.928 20.44a1.48 1.48 0 0 0 1.183 1.035a1.48 1.48 0 0 0 1.48-.621l3.078-4.44a.37.37 0 0 1 .31-.118a.43.43 0 0 1 .296.104l6.91 6.91a1.48 1.48 0 0 0 2.087 0l2.086-2.086a1.48 1.48 0 0 0-.074-2.101"/></svg>`;
      runtime.innerElement.style.borderRadius = "0";
      runtime.innerElement.style.border = "none";
      runtime.innerElement.style.backgroundColor = "transparent";
      runtime.innerElement.style.backdropFilter = "none";
      runtime.innerElement.style.boxShadow = "none";
      runtime.innerElement.style.filter = "drop-shadow(0 1px 2px rgba(0, 0, 0, 0.4))";
      runtime.innerElement.style.opacity = getBaseOpacity();
      setInnerSvg(runtime.innerElement, triangleSvg);
      return;
    }
    runtime.innerElement.style.borderRadius = "999px";
    runtime.innerElement.style.border = "none";
    runtime.innerElement.style.backgroundColor = runtime.options.color;
    runtime.innerElement.style.backdropFilter = "none";
    runtime.innerElement.style.filter = "none";
    runtime.innerElement.style.boxShadow = "0 2px 10px rgba(0, 0, 0, 0.18), inset 0 0 0 2px rgba(255, 255, 255, 0.55)";
    runtime.innerElement.style.opacity = getBaseOpacity();
  }
  function setInnerSvg(host, markup) {
    const parsed = new DOMParser().parseFromString(markup, "image/svg+xml");
    const svg = parsed.documentElement;
    if (svg.namespaceURI !== "http://www.w3.org/2000/svg" || svg.localName !== "svg") {
      return;
    }
    const imported = host.ownerDocument.importNode(svg, true);
    imported.setAttribute("width", "100%");
    imported.setAttribute("height", "100%");
    imported.style.display = "block";
    host.appendChild(imported);
  }
  function clearIdleHideTimer() {
    if (idleHideTimer !== null) {
      clearTimeout(idleHideTimer);
      idleHideTimer = null;
    }
  }
  function scheduleIdleHide() {
    clearIdleHideTimer();
    idleHideTimer = setTimeout(() => {
      idleHideTimer = null;
      if (!runtime.enabled || !runtime.innerElement) {
        return;
      }
      runtime.idleHidden = true;
      runtime.innerElement.style.transitionDuration = `${IDLE_FADE_OUT_MS}ms`;
      runtime.innerElement.style.transitionTimingFunction = PRESS_EASING;
      runtime.innerElement.style.opacity = "0";
    }, IDLE_HIDE_DELAY_MS);
  }
  function wakeFromIdle(options) {
    runtime.x = options.x;
    runtime.y = options.y;
    runtime.hasPosition = true;
    if (runtime.innerElement) {
      runtime.innerElement.style.transitionDuration = `${PRESS_DURATION_MS}ms`;
      runtime.innerElement.style.transitionTimingFunction = PRESS_EASING;
      runtime.innerElement.style.opacity = getBaseOpacity();
    }
  }
  function moveCursor(options) {
    if (!runtime.enabled) {
      return;
    }
    ensureCursorElement();
    const durationMs = computeDurationMs({ targetX: options.x, targetY: options.y });
    if (runtime.outerElement) {
      runtime.outerElement.style.transitionDuration = `${Math.round(durationMs)}ms`;
      runtime.outerElement.style.transitionTimingFunction = runtime.options.easing;
    }
    runtime.x = options.x;
    runtime.y = options.y;
    runtime.hasPosition = true;
    applyTranslate();
  }
  function setPressed(options) {
    if (!runtime.enabled || !runtime.innerElement) {
      return;
    }
    runtime.scale = options.pressed ? runtime.options.style === "dot" ? 0.92 : 0.95 : 1;
    runtime.innerElement.style.transitionDuration = `${PRESS_DURATION_MS}ms`;
    runtime.innerElement.style.transitionTimingFunction = PRESS_EASING;
    runtime.innerElement.style.opacity = options.pressed ? "1" : getBaseOpacity();
    applyScale();
  }
  function enable(options) {
    runtime.options = mergeOptions(options);
    runtime.enabled = true;
    ensureCursorElement();
    applyRuntimeVisualOptions();
    if (!runtime.hasPosition) {
      runtime.x = Math.round(window.innerWidth / 2);
      runtime.y = Math.round(window.innerHeight / 2);
      runtime.scale = 1;
      runtime.hasPosition = true;
    }
    runtime.idleHidden = false;
    if (runtime.innerElement) {
      runtime.innerElement.style.opacity = getBaseOpacity();
    }
    applyTranslate();
    applyScale();
    scheduleIdleHide();
  }
  function disable() {
    runtime.enabled = false;
    runtime.scale = 1;
    runtime.hasPosition = false;
    runtime.idleHidden = false;
    clearIdleHideTimer();
    if (runtime.outerElement) {
      runtime.outerElement.remove();
      runtime.outerElement = null;
      runtime.innerElement = null;
    }
  }
  function applyMouseAction(action) {
    if (!runtime.enabled) {
      return;
    }
    if (runtime.idleHidden) {
      runtime.idleHidden = false;
      wakeFromIdle({ x: action.x, y: action.y });
    }
    if (action.type === "move" || action.type === "wheel") {
      moveCursor({ x: action.x, y: action.y });
    } else if (action.type === "down") {
      moveCursor({ x: action.x, y: action.y });
      setPressed({ pressed: true });
    } else if (action.type === "up") {
      moveCursor({ x: action.x, y: action.y });
      setPressed({ pressed: false });
    }
    scheduleIdleHide();
  }
  var api = {
    enable,
    disable,
    applyMouseAction,
    isEnabled: () => {
      return runtime.enabled;
    }
  };
  if (isTopFrame) {
    globalThis.__playwriterGhostCursor = api;
    try {
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
          try {
            api.enable();
          } catch {}
        }, { once: true });
      } else {
        api.enable();
      }
    } catch {}
  }
})();
