// MAVIS dashboard v3.1.5 — robust initial synchronization.
(() => {
  let attempts = 0;
  const MAX_ATTEMPTS = 12; // ~30 seconds at 2.5 s polling

  function periodLabel(month) {
    if (month === monthKey()) return "Текущий месяц";
    if (month === monthKey(-1)) return "Предыдущий месяц";
    return month || "выбранный период";
  }

  loadingView = function(month) {
    return `<div class="loading-state"><div class="loading-spinner"></div><div>
      <div class="loading-title">Синхронизирую ${esc(periodLabel(month))}</div>
      <div class="muted">Интерфейс уже доступен. Первый расчёт Bitrix идёт в фоне; дальше данные будут открываться из кеша сразу.</div>
    </div></div>`;
  };

  function showSyncProblem(month, message, retryAfter = 0) {
    const retryText = retryAfter ? ` Повтор можно сделать через ${retryAfter} сек.` : "";
    $("#hub").innerHTML = `<div class="loading-state sync-problem">
      <div>
        <div class="loading-title">Не удалось закончить синхронизацию</div>
        <div class="muted">${esc(message || "Bitrix не вернул данные вовремя.")}${esc(retryText)}</div>
        <div style="margin-top:16px"><button id="syncRetryBtn" class="btn primary">Повторить</button></div>
      </div>
    </div>`;
    $("#liveDot").className = "bad";
    $("#liveText").textContent = "СИНХРОНИЗАЦИЯ ОСТАНОВЛЕНА · МОЖНО ПОВТОРИТЬ";
    $("#syncRetryBtn")?.addEventListener("click", () => {
      attempts = 0;
      state = null;
      load();
    });
  }

  // Replace the original unbounded polling loop.
  load = async function() {
    const month = $("#month").value;
    const period = $("#period").value;

    if (loadTimer) {
      clearTimeout(loadTimer);
      loadTimer = null;
    }
    if (loadController) loadController.abort();
    loadController = new AbortController();

    const sameState = state && state.month_key === month && (state.period || "month") === period;
    if (!sameState) {
      const cached = readBrowserSnapshot(month, period);
      if (cached) {
        state = cached.snapshot;
        renderAll();
        $("#liveDot").className = "";
        const ageMin = Math.max(0, Math.round((Date.now() - cached.saved_at) / 60000));
        $("#liveText").textContent = `ПОКАЗАН КЕШ БРАУЗЕРА${ageMin ? ` · ${ageMin} мин назад` : ""} · обновляю Bitrix`;
      } else {
        $("#hub").innerHTML = loadingView(month);
        $("#liveDot").className = "";
        $("#liveText").textContent = "СИНХРОНИЗАЦИЯ В ФОНЕ";
      }
    }

    try {
      const r = await fetch(
        `/api/snapshot?month=${encodeURIComponent(month)}&period=${encodeURIComponent(period)}${customQueryParams()}`,
        { cache: "no-store", signal: loadController.signal }
      );
      if (r.status === 401) {
        location.href = "/login";
        return;
      }

      const j = await r.json();
      const offlineSnapshot = r.headers.get("X-Mavis-Cache") === "offline";

      if (r.status === 202 || j.loading) {
        attempts += 1;
        $("#liveDot").className = "";
        const elapsed = Number(j.elapsed_seconds || 0);
        $("#liveText").textContent = state && state.month_key === month
          ? "ПОКАЗАНЫ ПОСЛЕДНИЕ ДАННЫЕ · Bitrix обновляется в фоне"
          : `BITRIX · ПЕРВИЧНАЯ СИНХРОНИЗАЦИЯ${elapsed ? ` · ${elapsed} сек` : ""}`;

        if (attempts >= MAX_ATTEMPTS) {
          showSyncProblem(
            month,
            "Расчёт идёт дольше обычного. Я остановил бесконечные повторы — можно повторить вручную."
          );
          return;
        }

        loadTimer = setTimeout(load, 2500);
        return;
      }

      if (!r.ok) {
        showSyncProblem(
          month,
          j.error || j.detail || "Ошибка синхронизации Bitrix.",
          Number(j.retry_after_seconds || 0)
        );
        return;
      }

      attempts = 0;
      state = j;
      saveBrowserSnapshot(j);
      renderAll();

      if (offlineSnapshot) {
        $("#liveDot").className = "bad";
        $("#liveText").textContent = "ПОКАЗАНА ПОСЛЕДНЯЯ ВЕРСИЯ · НЕТ СЕТИ";
      } else if (j.syncing) {
        $("#liveText").textContent = j.cached_snapshot
          ? "ПОКАЗАН ПОСЛЕДНИЙ SNAPSHOT · обновляю Bitrix в фоне"
          : "BITRIX ONLINE · обновляю в фоне";
      }
    } catch (e) {
      if (e.name === "AbortError") return;
      showSyncProblem(month, e.message || "Нет связи с сервером.");
    }
  };

  // Stop the timer created by app.js before this patch loaded and restart once.
  try {
    if (loadTimer) {
      clearTimeout(loadTimer);
      loadTimer = null;
    }
    if (loadController) loadController.abort();
  } catch (_) {}

  const marker = document.querySelector("#buildMarker");
  if (marker) marker.textContent = "v3.1.5";

  attempts = 0;
  load();
})();
