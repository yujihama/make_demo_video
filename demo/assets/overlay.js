// 録画用オーバーレイ: 章カード、同期マーカー、実マウスに追従する描画カーソル。
// ページ側の見た目には干渉しないよう、すべて pointer-events:none の最前面要素で描く。
(() => {
  if (window.__demo) return;
  const Z = 2147483646;
  const layer = (css) => {
    const el = document.createElement("div");
    el.style.cssText = `position:fixed;pointer-events:none;z-index:${Z};${css}`;
    document.documentElement.appendChild(el);
    return el;
  };

  // 実マウス追従カーソル（smooth モード用）。mousemove を拾って矢印を動かす。
  let follow = null;
  const cursorSvg =
    '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2 L4 19 L8.5 15 L11.5 22 L14.5 20.8 L11.6 14 L18 14 Z" fill="#111827" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  function enableFollow() {
    if (follow) return;
    follow = layer("left:0;top:0;width:26px;height:26px;transform:translate(-100px,-100px);transition:transform 16ms linear;filter:drop-shadow(0 1px 2px #0006)");
    follow.innerHTML = cursorSvg;
    window.addEventListener("mousemove", (e) => { follow.style.transform = `translate(${e.clientX - 3}px,${e.clientY - 2}px)`; }, true);
    window.addEventListener("mousedown", () => { follow.firstChild.style.transform = "scale(.88)"; }, true);
    window.addEventListener("mouseup", () => { follow.firstChild.style.transform = ""; }, true);
  }

  function chapter(title, description, duration) {
    return new Promise((done) => {
      const bg = layer("inset:0;background:rgba(15,23,42,.55);display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity .25s");
      bg.innerHTML = `<div style="background:#0f172a;color:#fff;border-radius:16px;padding:44px 72px;min-width:640px;text-align:center;box-shadow:0 20px 60px #0008;font-family:'Noto Sans CJK JP','Yu Gothic UI',Meiryo,sans-serif">
        <div style="font-size:52px;font-weight:700;letter-spacing:.04em">${title}</div>
        ${description ? `<div style="font-size:26px;margin-top:18px;color:#cbd5e1">${description}</div>` : ""}</div>`;
      requestAnimationFrame(() => (bg.style.opacity = "1"));
      setTimeout(() => { bg.style.opacity = "0"; setTimeout(() => { bg.remove(); done(); }, 260); }, duration);
    });
  }

  // 同期マーカー: 画面全体を指定色で塗る。動画上の最初の出現フレームで時刻を合わせる。
  function sync(color, ms) {
    return new Promise((done) => {
      const el = layer(`inset:0;background:${color}`);
      setTimeout(() => { el.remove(); done(); }, ms);
    });
  }

  window.__demo = { enableFollow, chapter, sync };
})();
