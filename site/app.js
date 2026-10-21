/* 源镜落地页交互：主题切换 / 滚动淡入 / 首屏轮播 / 吸顶导航 / 版本号 */
(function () {
  "use strict";

  const root = document.documentElement;
  const THEME_KEY = "yuanjing-site-theme";

  // ── 主题：跟随上次选择，默认深色 ──────────────────────
  let stored = null;
  try {
    stored = localStorage.getItem(THEME_KEY);
  } catch (error) {
    stored = null;
  }
  if (stored === "light" || stored === "dark") {
    root.dataset.theme = stored;
  }

  const themeButton = document.getElementById("themeToggle");
  if (themeButton) {
    themeButton.addEventListener("click", () => {
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch (error) {
        /* 隐私模式下写不了，忽略 */
      }
    });
  }

  // ── 滚动淡入（带兜底：观察器不触发也不会一直隐身）────
  const reveals = Array.from(document.querySelectorAll(".reveal"));
  const showAll = () => reveals.forEach((node) => node.classList.add("in"));
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            observer.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -6% 0px", threshold: 0.05 }
    );
    reveals.forEach((node) => observer.observe(node));
  }
  // 首屏立刻显示；其余交给观察器，1.2s 后仍未显示的兜底点亮
  reveals.slice(0, 6).forEach((node) => node.classList.add("in"));
  window.setTimeout(() => {
    reveals.forEach((node) => {
      const rect = node.getBoundingClientRect();
      if (rect.top < window.innerHeight && rect.bottom > 0) node.classList.add("in");
    });
  }, 1200);
  window.addEventListener("load", () => window.setTimeout(showAll, 2500));

  // ── 首屏叠层截图：点两侧、方向键、滑动都能切 ─────────
  const SLIDES = [
    {
      src: "assets/screen-agent.png",
      label: "AI 团队对话",
      caption: "同一个问题：内容分析师先读数据，传播策略师再给方向；右侧抖音热点同时带 AI 可用性判定",
    },
    {
      src: "assets/screen-overview.png",
      label: "数据概览",
      caption: "作品、互动人数、分析历史与待处理任务一屏看完，点指标即可查看统计口径",
    },
    {
      src: "assets/screen-works.png",
      label: "作品数据",
      caption: "作品表选中一行即可查看详情、采集评论区，或在聊天窗口里直接播放",
    },
  ];

  const deck = document.getElementById("heroDeck");
  const deckCards = deck ? Array.from(deck.querySelectorAll(".deck-card")) : [];
  const caption = document.getElementById("carouselCaption");
  const carousel = document.getElementById("heroCarousel");
  const dots = Array.from(document.querySelectorAll("#carouselDots .dot"));

  if (deckCards.length === SLIDES.length) {
    let current = 0;
    let timer = null;

    function render(index) {
      current = (index + SLIDES.length) % SLIDES.length;
      deckCards.forEach((card, position) => {
        const offset = (position - current + SLIDES.length) % SLIDES.length;
        // 0 = 中间，1 = 右侧待切，其余 = 左侧待切
        card.dataset.pos = offset === 0 ? "center" : offset === 1 ? "right" : offset === SLIDES.length - 1 ? "left" : "hidden";
      });
      if (caption) caption.textContent = SLIDES[current].caption;
      dots.forEach((dot, position) => dot.classList.toggle("is-active", position === current));
    }

    function step(delta) {
      render(current + delta);
    }

    function stop() {
      if (timer) window.clearInterval(timer);
      timer = null;
    }

    function start() {
      stop();
      timer = window.setInterval(() => step(1), 5600);
    }

    deckCards.forEach((card) => {
      card.addEventListener("click", () => {
        const pos = card.dataset.pos;
        if (pos === "right") step(1);
        else if (pos === "left") step(-1);
        start();
      });
    });

    dots.forEach((dot) => dot.addEventListener("click", () => {
      render(Number(dot.dataset.index));
      start();
    }));
    const prevButton = document.getElementById("carouselPrev");
    const nextButton = document.getElementById("carouselNext");
    if (prevButton) prevButton.addEventListener("click", () => { step(-1); start(); });
    if (nextButton) nextButton.addEventListener("click", () => { step(1); start(); });

    if (carousel) {
      carousel.addEventListener("mouseenter", stop);
      carousel.addEventListener("mouseleave", start);

      let touchStartX = null;
      carousel.addEventListener("touchstart", (event) => {
        touchStartX = event.touches[0].clientX;
        stop();
      }, { passive: true });
      carousel.addEventListener("touchend", (event) => {
        if (touchStartX === null) return;
        const delta = event.changedTouches[0].clientX - touchStartX;
        if (Math.abs(delta) > 40) step(delta < 0 ? 1 : -1);
        touchStartX = null;
        start();
      });
    }

    document.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (!carousel) return;
      const rect = carousel.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > window.innerHeight) return;
      step(event.key === "ArrowRight" ? 1 : -1);
      start();
    });

    render(0);
    start();
  }

  // ── 吸顶导航描边 ─────────────────────────────────────
  const nav = document.getElementById("nav");
  const onScroll = () => {
    if (!nav) return;
    nav.classList.toggle("scrolled", window.scrollY > 8);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // ── 版本号：读 GitHub Releases，失败就退回文字 ───────
  const versionNode = document.getElementById("verStable");
  const downloadButton = document.getElementById("dlStable");
  const REPO = "bixike3-droid/douyin-scout";
  // 自建域名上的下载目录：把打包好的 zip 放这里即可，改一行就能换渠道
  const DOWNLOAD_BASE = "download/";  // 同域直链：把 zip 放到站点的 download/ 目录即可
  const DOWNLOAD_ASSET = "download/yuanjing-latest.zip";

  async function loadLatest() {
    if (!versionNode) return;
    try {
      const response = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
        headers: { Accept: "application/vnd.github+json" },
      });
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      const name = data.tag_name || data.name || "latest";
      const published = data.published_at ? data.published_at.slice(0, 10) : "";
      versionNode.textContent = published ? `${name} · ${published}` : name;
      const asset = (data.assets || []).find((item) => /\.(zip|exe)$/i.test(item.name));
      if (asset && downloadButton) {
        downloadButton.href = asset.browser_download_url;
        downloadButton.textContent = "下载 " + asset.name;
      }
    } catch (error) {
      versionNode.textContent = "最新版本请见 Releases";
    }
  }

  if (DOWNLOAD_BASE) {
    // 自建下载渠道优先：包里只有一个文件，链接固定，不依赖 GitHub API
    if (downloadButton) {
      downloadButton.href = DOWNLOAD_BASE + "yuanjing-latest.zip";
      downloadButton.setAttribute("download", "yuanjing-0.10.2-windows-x64.zip");
    }
    if (versionNode) versionNode.textContent = "v0.10.2 · Windows · 118MB";
  } else if (location.protocol === "file:") {
    if (versionNode) versionNode.textContent = "最新版本请见 Releases";
  } else {
    loadLatest();
  }
})();
