const {$, $$, escapeHtml, riskLevel, formatDate, api, fileToBase64} = window.SignalUtils;
const voterToken = localStorage.getItem("signalwatch-voter") || crypto.randomUUID();
localStorage.setItem("signalwatch-voter", voterToken);
let feedCache = [];

const verdictClass = verdict => verdict === "Likely False" ? "verdict-false" : verdict === "Suspicious" ? "verdict-suspicious" : "verdict-true";

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove("show"), 2600);
}

function feedbackMarkup(post) {
  return `<div class="feedback"><span>Was this useful?</span>
    <button class="vote" data-post="${post.id}" data-vote="1">👍 <b>${post.thumbs_up || 0}</b></button>
    <button class="vote" data-post="${post.id}" data-vote="-1">👎 <b>${post.thumbs_down || 0}</b></button></div>`;
}

async function submitFeedback(button) {
  try {
    const postId = button.dataset.post;
    const result = await api(`/feedback/${postId}`, {
      method: "POST",
      body: JSON.stringify({vote: Number(button.dataset.vote), voter_token: voterToken})
    });
    $$(`.vote[data-post="${postId}"]`).forEach(item => {
      $("b", item).textContent = Number(item.dataset.vote) === 1 ? result.thumbs_up : result.thumbs_down;
    });
    toast("Feedback recorded — thank you.");
  } catch (error) { toast(error.message); }
}

document.addEventListener("click", event => {
  const vote = event.target.closest(".vote");
  if (vote) submitFeedback(vote);
});

function showPage(name) {
  $$(".page").forEach(page => page.classList.toggle("active", page.id === `page-${name}`));
  $$(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.page === name));
  $("#sidebar").classList.remove("open");
  if (name === "feed") loadFeed();
  if (name === "dashboard") loadDashboard();
}

$$('.nav-item').forEach(button => button.addEventListener("click", () => showPage(button.dataset.page)));
$("#menu-button").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
$("#claim-text").addEventListener("input", event => {
  $("#char-count").textContent = `${event.target.value.length.toLocaleString()} / 10,000`;
});
$("#claim-image").addEventListener("change", event => {
  const file = event.target.files[0];
  $("#image-name").textContent = file
    ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`
    : "Detect reused, unrelated, or misleading visuals";
});

async function loadStats() {
  try {
    const stats = await api("/stats");
    $("#side-total").textContent = stats.total_posts.toLocaleString();
    $("#side-risk").textContent = `${stats.average_risk}%`;
  } catch (_) { $(".status-row").textContent = "System unavailable"; }
}

$("#analyze-form").addEventListener("submit", async event => {
  event.preventDefault();
  const text = $("#claim-text").value.trim();
  const url = $("#claim-url").value.trim();
  const image = $("#claim-image").files[0];
  if (!text && !url && !image) { toast("Add claim text, a source URL, or an image first."); return; }
  if (image && image.size > 5 * 1024 * 1024) { toast("The image must be 5 MB or smaller."); return; }

  const button = $("#analyze-button");
  const result = $("#analysis-result");
  button.disabled = true;
  $("span", button).textContent = "Scanning signals…";
  result.innerHTML = `<div class="panel skeleton" style="margin-top:24px"></div>`;
  try {
    const imageBase64 = image ? await fileToBase64(image) : null;
    const data = await api("/analyze", {
      method: "POST",
      body: JSON.stringify({text, url: url || null, image_base64: imageBase64, image_mime_type: image?.type || null})
    });
    renderAnalysis(data);
    loadStats();
  } catch (error) {
    result.innerHTML = `<div class="panel error">${escapeHtml(error.message)}</div>`;
  } finally {
    button.disabled = false;
    $("span", button).textContent = "Run intelligence scan";
  }
});

function renderAnalysis(data) {
  const evidence = (data.evidence || []).map(item => `<article class="evidence">
    <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a>
    <p>${escapeHtml(item.snippet)}</p><span class="stance">${escapeHtml(item.type || "fact-check")} · ${Math.round((item.similarity_score || 0) * 100)}% match</span>
  </article>`).join("");
  const cues = (data.highlights || []).map(item => `<span class="cue">${escapeHtml(item.phrase)} · ${escapeHtml(item.category)}</span>`).join("");
  const image = data.image_analysis;
  const vision = image ? `<section class="vision-card"><header><h3>Visual context analysis</h3>
    <span class="badge ${image.mismatch_score >= .7 ? "high" : image.mismatch_score >= .4 ? "medium" : "low"}">${escapeHtml(image.relationship.replaceAll("_", " "))}</span></header>
    <p>${escapeHtml(image.explanation)}</p><small>${escapeHtml(image.image_description)}</small></section>` : "";
  const domain = data.domain_analysis?.features || {};
  const domainSignals = domain.domain ? `<div class="domain-signals">
    <span class="signal-chip">ML credibility ${Math.round(data.domain_analysis.score * 100)}%</span>
    <span class="signal-chip">TLS ${domain.tls_valid ? "valid" : "not verified"}</span>
    <span class="signal-chip">RDAP ${domain.whois_rdap_available ? "found" : "unavailable"}</span>
    <span class="signal-chip">Age ${domain.age_days == null ? "unknown" : `${domain.age_days.toLocaleString()} days`}</span></div>` : "";

  $("#analysis-result").innerHTML = `<article class="panel result">
    <div class="result-top"><div class="result-cell"><small>Verdict</small><strong class="${verdictClass(data.verdict)}">${escapeHtml(data.verdict)}</strong></div>
    <div class="result-cell"><small>Risk score</small><strong class="risk-value ${riskLevel(data.overall_risk)}">${data.overall_risk}%</strong></div>
    <div class="result-cell"><small>Viral Risk (ASM)</small><strong class="risk-value ${riskLevel(data.viral_propagation_risk || 0)}">${data.viral_propagation_risk || 0}%</strong></div>
    <div class="result-cell"><small>Confidence</small><strong>${data.confidence}%</strong></div></div>
    <div class="result-body"><h3>Why the system reached this verdict</h3><p>${escapeHtml(data.explanation || "No explanation available.")}</p>
    ${domainSignals}${vision}${cues ? `<div class="cue-list">${cues}</div>` : ""}<h3>Corroborating evidence</h3>
    ${evidence ? `<div class="evidence-grid">${evidence}</div>` : `<p>No explicit fact-check matches were found.</p>`}${feedbackMarkup(data)}</div>
  </article>`;
}

async function loadFeed() {
  try {
    feedCache = await api("/feed");
    const select = $("#verdict-filter");
    const current = select.value;
    const verdicts = [...new Set(feedCache.map(item => item.verdict))].sort();
    select.innerHTML = `<option value="">All classifications</option>` + verdicts.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
    select.value = current;
    renderFeed();
  } catch (error) { $("#feed-list").innerHTML = `<div class="panel error">${escapeHtml(error.message)}</div>`; }
}

function renderFeed() {
  const verdict = $("#verdict-filter").value;
  const rows = verdict ? feedCache.filter(item => item.verdict === verdict) : feedCache;
  $("#feed-count").textContent = `${rows.length} result${rows.length === 1 ? "" : "s"}`;
  $("#feed-list").innerHTML = rows.length ? rows.map(item => `<article class="panel feed-card">
    <div class="feed-meta"><span class="badge ${riskLevel(item.overall_risk)}">${escapeHtml(item.verdict)}</span><span>${formatDate(item.timestamp)}</span><span>${escapeHtml(item.domain || "Direct text")}</span></div>
    <h2 class="feed-title">${escapeHtml(item.claim_text || item.text)}</h2><p class="feed-explanation">${escapeHtml(item.explanation || "")}</p>${feedbackMarkup(item)}
  </article>`).join("") : `<div class="panel empty">No results match this filter.</div>`;
  $$('.export-actions a').forEach(link => {
    link.href = `/export/${link.textContent.toLowerCase()}${verdict ? `?verdict=${encodeURIComponent(verdict)}` : ""}`;
  });
}
$("#verdict-filter").addEventListener("change", renderFeed);

async function loadDashboard() {
  try { renderDashboard(await api("/trending")); }
  catch (error) { $("#trend-list").innerHTML = `<div class="panel error">${escapeHtml(error.message)}</div>`; }
}

function renderDashboard(clusters) {
  const highRisk = clusters.filter(cluster => cluster.average_risk >= 70).length;
  const lastHour = clusters.reduce((sum, cluster) => sum + cluster.post_count_1h, 0);
  $("#dashboard-metrics").innerHTML = `<div class="panel metric"><small>Tracked narratives</small><strong>${clusters.length}</strong></div><div class="panel metric"><small>High-risk clusters</small><strong>${highRisk}</strong></div><div class="panel metric"><small>Posts in last hour</small><strong>${lastHour}</strong></div>`;
  $("#trend-list").innerHTML = clusters.length ? clusters.map(cluster => {
    const emerging = (cluster.post_count_1h >= 2 || cluster.post_count_6h >= 3) && cluster.average_risk >= 60;
    return `<article class="panel trend-card ${emerging ? "emerging" : ""}"><div class="trend-head"><div><div class="trend-meta">${emerging ? `<span class="badge high">Emerging threat</span>` : `<span class="badge ${riskLevel(cluster.average_risk)}">Monitoring</span>`}<span>${cluster.post_count} total signals</span></div><h3>${escapeHtml(cluster.claim_title)}</h3></div><strong class="risk-index ${riskLevel(cluster.average_risk)}">${Math.round(cluster.average_risk)}%</strong></div><div class="velocity"><div><strong>${cluster.post_count_1h}</strong><small>Last hour</small></div><div><strong>${cluster.post_count_6h}</strong><small>Last 6 hours</small></div><div><strong>${cluster.post_count_24h}</strong><small>Last 24 hours</small></div></div><div class="domains">Sources: ${cluster.domains.length ? cluster.domains.map(escapeHtml).join(" · ") : "Direct text submissions"}</div></article>`;
  }).join("") : `<div class="panel empty">No narrative clusters detected yet.</div>`;
}

loadStats();
const eventSource = new EventSource("/events");
eventSource.addEventListener("update", () => {
  loadStats();
  if ($("#page-feed").classList.contains("active")) loadFeed();
  if ($("#page-dashboard").classList.contains("active")) loadDashboard();
});
eventSource.onerror = () => { /* Native EventSource reconnects automatically. */ };
