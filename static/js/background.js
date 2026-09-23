/* ================================================================
   Futuristic Business-Data Background — vertical glowing data bars
   + perspective data-flow lines converging toward a central point,
   on a deep navy/midnight base. Matches the reference "data tunnel"
   composition: no world map, no nodes, no HUD panels — a clean,
   enterprise-grade animated backdrop for dashboard UI.
================================================================= */
(function () {
  const canvas = document.getElementById("bg-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  let W, H, DPR;
  let bars = [];
  let rays = [];

  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = canvas.clientWidth;
    H = canvas.clientHeight;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    layout();
  }

  function horizonY() {
    return H * 0.4;
  }
  function vanishX() {
    return W * 0.52;
  }

  function layout() {
    const hy = horizonY();

    // Vertical data bars hanging from the top down toward the horizon line.
    bars = [];
    const count = Math.max(34, Math.floor(W / 32));
    for (let i = 0; i < count; i++) {
      const x = (i + 0.5) * (W / count) + (Math.random() - 0.5) * 14;
      const bright = Math.random() < 0.4;
      const topY = hy * (0.02 + Math.random() * 0.5);
      bars.push({
        x,
        topY,
        bottomY: hy - Math.random() * hy * 0.03,
        width: bright ? 2.2 + Math.random() * 1.8 : 1 + Math.random(),
        bright,
        hueShift: Math.random(),
        phase: Math.random() * Math.PI * 2,
        speed: 0.4 + Math.random() * 0.6,
      });
    }

    // Perspective floor rays from the bottom edge converging near (vanishX, horizonY)
    rays = [];
    const rayCount = 52;
    for (let i = 0; i < rayCount; i++) {
      const t = i / (rayCount - 1);
      const bottomX = t * W * 1.15 - W * 0.075;
      const bright = Math.random() < 0.6;
      rays.push({
        bottomX,
        bright,
        width: bright ? 1.8 + Math.random() * 1.6 : 0.6 + Math.random() * 0.6,
        opacity: bright ? 0.48 + Math.random() * 0.3 : 0.1 + Math.random() * 0.14,
        particles: bright
          ? Array.from({ length: 2 + Math.floor(Math.random() * 2) }, () => Math.random())
          : [],
        speed: 0.5 + Math.random() * 0.6,
      });
    }
  }

  function drawBackground() {
    const hy = horizonY();
    const vx = vanishX();

    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, "#02040a");
    g.addColorStop(0.55, "#040814");
    g.addColorStop(1, "#050b1c");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);

    // Central convergence glow, integrated low-key (no big circle)
    const glow = ctx.createRadialGradient(vx, hy, 4, vx, hy, W * 0.46);
    glow.addColorStop(0, "rgba(50,140,220,0.34)");
    glow.addColorStop(0.4, "rgba(20,70,140,0.16)");
    glow.addColorStop(1, "rgba(4,8,20,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, W, H);
  }

  function drawBars(t) {
    bars.forEach((b) => {
      const pulse = 0.75 + 0.25 * Math.sin(t * 0.0007 * b.speed + b.phase);
      const alphaTop = b.bright ? 0.02 : 0.015;
      const alphaMid = (b.bright ? 0.72 : 0.2) * pulse;
      const colorMid = b.bright
        ? `rgba(140, 225, 255, ${alphaMid})`
        : `rgba(60, 130, 200, ${alphaMid})`;

      const grad = ctx.createLinearGradient(0, b.topY, 0, b.bottomY);
      grad.addColorStop(0, `rgba(80,170,230,${alphaTop})`);
      grad.addColorStop(0.55, colorMid);
      grad.addColorStop(1, "rgba(80,170,230,0.02)");

      ctx.save();
      if (b.bright) {
        ctx.shadowColor = "rgba(110,210,255,0.65)";
        ctx.shadowBlur = 14;
      }
      ctx.fillStyle = grad;
      ctx.fillRect(b.x - b.width / 2, b.topY, b.width, b.bottomY - b.topY);
      ctx.restore();
    });
  }

  function drawRays(t) {
    const hy = horizonY();
    const vx = vanishX();

    rays.forEach((r) => {
      ctx.beginPath();
      ctx.moveTo(vx, hy);
      ctx.lineTo(r.bottomX, H);
      const grad = ctx.createLinearGradient(vx, hy, r.bottomX, H);
      const c = r.bright ? "130,215,255" : "50,110,180";
      grad.addColorStop(0, `rgba(${c},${r.opacity * 0.2})`);
      grad.addColorStop(0.6, `rgba(${c},${r.opacity})`);
      grad.addColorStop(1, `rgba(${c},${r.opacity * 0.75})`);
      ctx.strokeStyle = grad;
      ctx.lineWidth = r.width;
      ctx.stroke();

      // faster traveling particles along bright rays (lively data flow)
      if (r.bright && r.particles.length) {
        for (let i = 0; i < r.particles.length; i++) {
          r.particles[i] = (r.particles[i] + 0.0065 * r.speed) % 1;
          const ft = r.particles[i];
          const px = vx + (r.bottomX - vx) * ft;
          const py = hy + (H - hy) * ft;
          const fade = Math.min(1, ft * 6) * Math.min(1, (1 - ft) * 4);
          ctx.beginPath();
          ctx.arc(px, py, 1.8, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(200,240,255,${0.9 * fade})`;
          ctx.shadowColor = "rgba(150,220,255,0.9)";
          ctx.shadowBlur = 6;
          ctx.fill();
          ctx.shadowBlur = 0;
        }
      }
    });

    // faint horizon line
    const hg = ctx.createLinearGradient(0, hy, W, hy);
    hg.addColorStop(0, "rgba(60,130,200,0)");
    hg.addColorStop(0.5, "rgba(100,190,255,0.18)");
    hg.addColorStop(1, "rgba(60,130,200,0)");
    ctx.strokeStyle = hg;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, hy);
    ctx.lineTo(W, hy);
    ctx.stroke();
  }

  function frame(t) {
    ctx.clearRect(0, 0, W, H);
    drawBackground();
    drawRays(t);
    drawBars(t);
    requestAnimationFrame(frame);
  }

  window.addEventListener("resize", resize);
  resize();
  requestAnimationFrame(frame);
})();
