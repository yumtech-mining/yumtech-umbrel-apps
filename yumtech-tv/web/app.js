/* YUMLU TV — browser-side HLS player and IPTV-org playlist reader */
(() => {
  "use strict";

  const PLAYLIST_URL = "https://iptv-org.github.io/iptv/countries/tr.m3u";
  const FALLBACK_CHANNELS = [
    { id: "TRT1-fallback", name: "TRT 1", group: "general", url: "https://tv-trt1.medya.trt.com.tr/master.m3u8", logo: "", note: "Resmî TRT akışı" },
    { id: "TRTHaber-fallback", name: "TRT Haber", group: "news", url: "https://tv-trthaber.medya.trt.com.tr/master.m3u8", logo: "", note: "Resmî TRT akışı" },
    { id: "TRTBelgesel-fallback", name: "TRT Belgesel", group: "general", url: "https://tv-trtbelgesel.medya.trt.com.tr/master.m3u8", logo: "", note: "Resmî TRT akışı" },
    { id: "TRTSpor-fallback", name: "TRT Spor", group: "sports", url: "https://tv-trt3.live.trt.com.tr/master.m3u8", logo: "", note: "Resmî TRT akışı" },
    { id: "ATV-fallback", name: "ATV", group: "general", url: "https://rnttwmjcin.turknet.ercdn.net/lcpmvefbyo/atv/atv_1080p.m3u8", logo: "", note: "Açık internet akışı" },
    { id: "Ahaber-fallback", name: "A Haber", group: "news", url: "https://rnttwmjcin.turknet.ercdn.net/lcpmvefbyo/ahaber/ahaber.m3u8", logo: "", note: "Açık internet akışı" },
    { id: "ASpor-fallback", name: "A Spor", group: "sports", url: "https://rnttwmjcin.turknet.ercdn.net/lcpmvefbyo/aspor/aspor.m3u8", logo: "", note: "Açık internet akışı" },
    { id: "KanalD-fallback", name: "Kanal D", group: "general", url: "https://demiroren.daioncdn.net/kanald/kanald.m3u8?app=kanald_web&ce=3", logo: "", note: "Açık internet akışı" },
    { id: "Kanal7-fallback", name: "Kanal 7", group: "general", url: "https://kanal7-live.daioncdn.net/kanal7/kanal7.m3u8", logo: "", note: "Açık internet akışı" },
    { id: "StarTV-fallback", name: "Star TV", group: "general", url: "https://dogus.daioncdn.net/startv/startv_720p.m3u8", logo: "", note: "Açık internet akışı" },
    { id: "TV8-fallback", name: "TV8", group: "general", url: "https://tv8.daioncdn.net/tv8/tv8.m3u8?app=web&ce=3", logo: "", note: "Açık internet akışı" },
    { id: "NTV-fallback", name: "NTV", group: "news", url: "https://dogus.daioncdn.net/ntv/ntv.m3u8?app=ntv_web", logo: "", note: "Açık internet akışı" },
    { id: "HalkTV-fallback", name: "Halk TV", group: "news", url: "https://halktv-live.daioncdn.net/halktv/halktv.m3u8", logo: "", note: "Açık internet akışı" },
    { id: "Tele1-fallback", name: "Tele 1", group: "news", url: "https://tele1-live.ercdn.net/tele1/tele1.m3u8", logo: "", note: "Açık internet akışı" },
    { id: "BloombergHT-fallback", name: "Bloomberg HT", group: "news", url: "https://ciner-live.daioncdn.net/bloomberght/bloomberght.m3u8", logo: "", note: "Açık internet akışı" },
    { id: "KralPop-fallback", name: "KRAL Pop TV", group: "music", url: "https://dogus-live.daioncdn.net/kralpoptv/playlist.m3u8", logo: "", note: "Açık internet akışı" },
    { id: "PowerTurk-fallback", name: "Power Türk", group: "music", url: "https://livetv.powerapp.com.tr/powerturkTV/powerturkhd.smil/playlist.m3u8", logo: "", note: "Açık internet akışı" },
    { id: "Diyanet-fallback", name: "Diyanet TV", group: "general", url: "https://eustr73.mediatriple.net/videoonlylive/mtikoimxnztxlive/broadcast_5e3bf95a47e07.smil/playlist.m3u8", logo: "", note: "Açık internet akışı" },
    { id: "TV24-fallback", name: "TV 24", group: "news", url: "https://turkmedya-live.ercdn.net/tv24/tv24.m3u8", logo: "", note: "Açık internet akışı" }
  ];

  const state = { channels: [], current: null, hls: null, filter: "all", search: "", toastTimer: null };
  const $ = (selector) => document.querySelector(selector);
  const channelList = $("#channelList");
  const video = $("#player");
  const playerShell = $("#playerShell");
  const placeholder = $("#playerPlaceholder");
  const overlay = $("#playerOverlay");
  const overlayText = $("#overlayText");

  function attr(line, key) {
    const match = line.match(new RegExp(key + '="([^"]*)"', "i"));
    return match ? match[1].trim() : "";
  }

  function cleanName(value) {
    return String(value || "")
      .replace(/\s*\([^)]*(?:p|SD|HD|UHD|4K)[^)]*\)/gi, "")
      .replace(/\s*\[(?:Not 24\/7|Geo-blocked)\]/gi, "")
      .replace(/\s{2,}/g, " ")
      .trim();
  }

  function classify(group, name) {
    const value = (String(group || "") + " " + String(name || "")).toLocaleLowerCase("tr-TR");
    if (/haber|news|ekonomi|business/.test(value)) return "news";
    if (/spor|sport|futbol/.test(value)) return "sports";
    if (/müzik|muzik|music|power|kral|number 1/.test(value)) return "music";
    return "general";
  }

  function qualityScore(channel) {
    return (channel.url.startsWith("https://") ? 3 : 0) + (channel.url.includes(".m3u8") ? 2 : 0) + (channel.blocked ? -3 : 0);
  }

  function parseM3U(text) {
    const lines = String(text || "").split(/\r?\n/);
    const parsed = [];
    let info = "";
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) continue;
      if (line.toUpperCase().startsWith("#EXTINF")) {
        info = line;
        continue;
      }
      if (!info || line.startsWith("#")) continue;
      const comma = info.indexOf(",");
      const rawName = comma >= 0 ? info.slice(comma + 1).trim() : "Bilinmeyen kanal";
      const blocked = /\[Geo-blocked\]/i.test(rawName);
      parsed.push({
        id: attr(info, "tvg-id") || rawName,
        name: cleanName(rawName) || rawName,
        group: classify(attr(info, "group-title"), rawName),
        groupLabel: attr(info, "group-title") || "Genel",
        logo: attr(info, "tvg-logo"),
        url: line,
        blocked,
        note: blocked ? "Bölgesel kısıt olabilir" : /\[Not 24\/7\]/i.test(rawName) ? "7/24 yayın olmayabilir" : "HLS canlı yayın"
      });
      info = "";
    }
    const unique = new Map();
    for (const channel of parsed) {
      const key = channel.id.toLocaleLowerCase("tr-TR");
      const previous = unique.get(key);
      if (!previous || qualityScore(channel) > qualityScore(previous)) unique.set(key, channel);
    }
    return Array.from(unique.values()).filter((channel) => channel.url.startsWith("http"));
  }

  function initials(name) {
    const words = String(name || "TV").split(/\s+/).filter(Boolean);
    return (words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)).toLocaleUpperCase("tr-TR");
  }

  function filteredChannels() {
    const needle = state.search.toLocaleLowerCase("tr-TR");
    return state.channels.filter((channel) => {
      const matchesFilter = state.filter === "all" || channel.group === state.filter;
      const matchesSearch = !needle || channel.name.toLocaleLowerCase("tr-TR").includes(needle) || channel.groupLabel.toLocaleLowerCase("tr-TR").includes(needle);
      return matchesFilter && matchesSearch;
    });
  }

  function makeInitials(name) {
    const badge = document.createElement("span");
    badge.className = "channel-initials";
    badge.textContent = initials(name);
    badge.setAttribute("aria-hidden", "true");
    return badge;
  }

  function renderChannels() {
    const list = filteredChannels();
    $("#channelCount").textContent = String(state.channels.length || "—");
    channelList.replaceChildren();
    if (!list.length) {
      const empty = document.createElement("div");
      empty.className = "list-empty";
      empty.textContent = state.channels.length ? "Aramanıza uygun kanal bulunamadı." : "Kanal listesi alınamadı.";
      channelList.append(empty);
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const channel of list) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "channel-item" + (state.current && state.current.id === channel.id ? " is-selected" : "");
      item.setAttribute("role", "listitem");
      item.setAttribute("aria-label", channel.name + " kanalını aç");
      item.addEventListener("click", () => selectChannel(channel));
      if (channel.logo) {
        const image = document.createElement("img");
        image.className = "channel-logo";
        image.src = channel.logo;
        image.alt = "";
        image.loading = "lazy";
        image.addEventListener("error", () => image.replaceWith(makeInitials(channel.name)), { once: true });
        item.append(image);
      } else {
        item.append(makeInitials(channel.name));
      }
      const copy = document.createElement("span");
      copy.className = "channel-copy";
      const name = document.createElement("span");
      name.className = "channel-name";
      name.textContent = channel.name;
      const meta = document.createElement("span");
      meta.className = "channel-meta";
      meta.textContent = channel.groupLabel || (channel.group === "general" ? "Genel" : channel.group);
      copy.append(name, meta);
      item.append(copy);
      const live = document.createElement("span");
      live.className = "channel-live";
      live.setAttribute("aria-hidden", "true");
      item.append(live);
      fragment.append(item);
    }
    channelList.append(fragment);
  }

  function setOverlay(visible, text) {
    overlay.hidden = !visible;
    if (text) overlayText.textContent = text;
  }

  function notify(message) {
    const toast = $("#toast");
    toast.textContent = message;
    toast.classList.add("is-visible");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 3600);
  }

  function releasePlayer() {
    if (state.hls) {
      state.hls.destroy();
      state.hls = null;
    }
    video.pause();
    video.removeAttribute("src");
    video.load();
  }

  function playerError(message) {
    setOverlay(false);
    placeholder.classList.remove("hidden");
    $("#liveState").textContent = "Yayın açılamadı";
    $("#liveState").style.color = "var(--danger)";
    notify(message + " Kaynak bağlantısını deneyebilirsiniz.");
  }

  function playAfterReady() {
    video.play().catch(() => notify("Tarayıcı otomatik oynatmayı engelledi; oynat düğmesine basın."));
  }

  function selectChannel(channel) {
    state.current = channel;
    renderChannels();
    placeholder.classList.add("hidden");
    setOverlay(true, "Yayın yükleniyor…");
    $("#currentTitle").textContent = channel.name;
    $("#currentMeta").textContent = channel.note || "HLS canlı yayın";
    $("#streamGroup").textContent = channel.groupLabel || (channel.group === "general" ? "Genel" : channel.group);
    $("#streamHost").textContent = (() => { try { return new URL(channel.url).host; } catch (_) { return "Kaynak bağlantısı"; } })();
    $("#streamNote").textContent = channel.blocked ? "Bölgesel kısıt olabilir" : "HLS canlı yayın";
    $("#liveState").textContent = "Bağlanıyor…";
    $("#liveState").style.color = "var(--orange)";
    const external = $("#openExternal");
    external.hidden = false;
    external.onclick = () => window.open(channel.url, "_blank", "noopener,noreferrer");

    releasePlayer();
    video.onerror = () => playerError("Bu yayın tarayıcıda açılamadı.");
    video.onwaiting = () => { if (state.current === channel) setOverlay(true, "Yayın arabelleğe alınıyor…"); };
    video.onplaying = () => {
      if (state.current === channel) {
        setOverlay(false);
        $("#liveState").textContent = "Canlı yayında";
        $("#liveState").style.color = "var(--cyan)";
      }
    };

    if (window.Hls && window.Hls.isSupported()) {
      const hls = new window.Hls({ enableWorker: true, lowLatencyMode: true, backBufferLength: 30, manifestLoadingTimeOut: 12000 });
      state.hls = hls;
      hls.on(window.Hls.Events.ERROR, (_, data) => {
        if (data && data.fatal && state.current === channel) {
          if (data.type === window.Hls.ErrorTypes.NETWORK_ERROR) {
            hls.startLoad();
            setOverlay(true, "Ağ bağlantısı yeniden deneniyor…");
          } else {
            playerError("Yayın bağlantısı reddedildi veya sona erdi.");
          }
        }
      });
      hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
        if (state.current === channel) {
          $("#liveState").textContent = "Hazır";
          $("#liveState").style.color = "var(--cyan)";
          playAfterReady();
        }
      });
      hls.loadSource(channel.url);
      hls.attachMedia(video);
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = channel.url;
      video.onloadedmetadata = () => {
        if (state.current === channel) playAfterReady();
      };
    } else {
      playerError("Bu tarayıcı HLS oynatmayı desteklemiyor.");
    }
  }

  async function fetchWithTimeout(url, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { signal: controller.signal, cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      return await response.text();
    } finally {
      clearTimeout(timer);
    }
  }

  async function loadChannels() {
    const refresh = $("#refreshBtn");
    refresh.disabled = true;
    refresh.setAttribute("aria-busy", "true");
    $("#sourceStatus").textContent = "Liste yenileniyor…";
    channelList.innerHTML = '<div class="list-loading"><span></span><span></span><span></span><span></span><span></span></div>';
    try {
      const text = await fetchWithTimeout(PLAYLIST_URL, 15000);
      const parsed = parseM3U(text);
      if (!parsed.length) throw new Error("Kanal bulunamadı");
      state.channels = parsed;
      $("#sourceStatus").textContent = parsed.length + " kanal · güncel";
      notify(parsed.length + " Türkiye kanalı yüklendi.");
    } catch (_) {
      state.channels = FALLBACK_CHANNELS;
      $("#sourceStatus").textContent = "Yedek liste · bağlantı bekleniyor";
      notify("Ana kanal listesi alınamadı; yedek liste gösteriliyor.");
    } finally {
      refresh.disabled = false;
      refresh.removeAttribute("aria-busy");
      renderChannels();
      if (!state.current && state.channels.length) selectChannel(state.channels[0]);
    }
  }

  $("#refreshBtn").addEventListener("click", loadChannels);
  $("#searchInput").addEventListener("input", (event) => {
    state.search = event.target.value.trim();
    renderChannels();
  });
  document.querySelectorAll(".filter-chip").forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter || "all";
      document.querySelectorAll(".filter-chip").forEach((chip) => chip.classList.toggle("is-active", chip === button));
      renderChannels();
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && document.activeElement !== $("#searchInput")) {
      event.preventDefault();
      $("#searchInput").focus();
    }
    if (event.key.toLowerCase() === "f" && document.activeElement !== $("#searchInput")) toggleFullscreen();
  });
  playerShell.addEventListener("dblclick", toggleFullscreen);
  playerShell.addEventListener("keydown", (event) => {
    if (event.key.toLowerCase() === "f") toggleFullscreen();
  });

  function toggleFullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else if (playerShell.requestFullscreen) {
      playerShell.requestFullscreen().catch(() => {});
    }
  }

  loadChannels();
})();
