(function () {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const escapeHtml = (value = "") => String(value).replace(/[&<>'"]/g, char => ({
    "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;"
  })[char]);
  const riskLevel = risk => risk >= 70 ? "high" : risk >= 40 ? "medium" : "low";
  const formatDate = value => value
    ? new Date(value.replace(" ", "T") + "Z").toLocaleString([], {dateStyle:"medium", timeStyle:"short"})
    : "Unknown time";

  const API_BASE_URL = "http://127.0.0.1:8001";
  async function api(path, options = {}) {
    const response = await fetch(API_BASE_URL + path, {headers:{"Content-Type":"application/json"}, ...options});
    if (!response.ok) {
      let detail = "Request failed";
      try { detail = (await response.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return response.json();
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1]);
      reader.onerror = () => reject(new Error("Could not read the selected image"));
      reader.readAsDataURL(file);
    });
  }

  window.SignalUtils = {$, $$, escapeHtml, riskLevel, formatDate, api, fileToBase64};
})();
