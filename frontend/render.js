const STATUS_LABELS = {
  comparable: { text: "Подходит полностью", dot: "ok" },
  partially_comparable: { text: "Подходит с оговоркой", dot: "warn" },
  not_comparable: { text: "Не подходит под заказ", dot: "err" },
};

const COMPLETENESS_LABELS = {
  complete: "все условия известны",
  partial: "часть сведений не указана",
  insufficient: "не хватает цены или условий",
};

const PROVIDER_TYPE_LABELS = {
  company: "Компания",
  private: "Частный исполнитель",
};

const UNIT_RU_LABELS = {
  sqm: "м²",
  hour: "ч",
  minute: "мин",
  room: "комн.",
  unit: "шт.",
  month: "мес.",
  session: "сеанс",
  km: "км",
  meter: "м",
  kg: "кг",
  gram: "г",
  fixed: "заказ",
};

function formatUnitsInText(text) {
  let out = String(text ?? "");
  for (const [eng, ru] of Object.entries(UNIT_RU_LABELS)) {
    out = out.replace(new RegExp(`\\b${eng}\\b`, "g"), ru);
  }
  return out;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatMoney(value) {
  if (value === null || value === undefined) return null;
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 2,
  }).format(num);
}

export function renderOffersList(container, offers, { onEdit, onRemove }) {
  const countEl = document.getElementById("offers-count");
  if (countEl) {
    countEl.textContent = String(offers.length);
  }

  if (!offers.length) {
    container.innerHTML =
      '<p class="field-hint">Пока нет предложений. Добавьте исполнителя выше, загрузите из архива или откройте пример смет.</p>';
    return;
  }

  container.innerHTML = offers
    .map((offer, index) => {
      const priceStr =
        offer.base_price !== null && offer.base_price !== undefined
          ? `${formatMoney(offer.base_price)} ₽ / ${escapeHtml(offer.pricing_unit || "?")}`
          : "Цена не указана";
      const surchargesCount = offer.surcharges ? offer.surcharges.length : 0;
      const surchargeText = surchargesCount ? ` · доплат: ${surchargesCount}` : "";
      return `
        <div class="offer-chip">
          <div class="offer-chip-main">
            <div class="offer-chip-title">${escapeHtml(offer.provider_name)} — ${escapeHtml(offer.service_title)}</div>
            <div class="offer-chip-sub tabular">${priceStr}${surchargeText}</div>
          </div>
          <div class="offer-chip-actions">
            <button type="button" class="btn btn-ghost btn-sm" data-edit-offer="${index}" aria-label="Изменить предложение ${escapeHtml(offer.provider_name)}">
              Изменить
            </button>
            <button type="button" class="btn btn-ghost btn-sm" data-remove-offer="${index}" aria-label="Удалить предложение ${escapeHtml(offer.provider_name)}">
              Удалить
            </button>
          </div>
        </div>
      `;
    })
    .join("");

  container.querySelectorAll("[data-edit-offer]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.getAttribute("data-edit-offer"));
      onEdit(idx);
    });
  });

  container.querySelectorAll("[data-remove-offer]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.getAttribute("data-remove-offer"));
      onRemove(idx);
    });
  });
}

const COPY_QUESTIONS_LABEL = "Скопировать вопросы подрядчику";

async function copyQuestionsText(text, buttonEl) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const temp = document.createElement("textarea");
      temp.value = text;
      temp.style.position = "fixed";
      temp.style.opacity = "0";
      document.body.appendChild(temp);
      temp.select();
      document.execCommand("copy");
      document.body.removeChild(temp);
    }
    if (buttonEl._copyTimer) {
      window.clearTimeout(buttonEl._copyTimer);
    }
    buttonEl.textContent = "Скопировано";
    buttonEl._copyTimer = window.setTimeout(() => {
      buttonEl.textContent = COPY_QUESTIONS_LABEL;
      buttonEl._copyTimer = null;
    }, 1800);
  } catch {
    buttonEl.textContent = "Не удалось скопировать";
  }
}

function renderSimilarityBreakdown(breakdown) {
  if (!breakdown) return "";
  const factors = [
    { label: "Покрытие работ (45%)", data: breakdown.scope_coverage },
    { label: "Прозрачность прайса (30%)", data: breakdown.price_transparency },
    { label: "Гео и формат (15%)", data: breakdown.geo_and_format },
    { label: "Единицы и объём (10%)", data: breakdown.unit_and_volume },
  ];
  return `
    <details class="similarity-details">
      <summary class="field-hint" style="cursor: pointer;">Разбивка сходства по 4 метрикам</summary>
      <div class="similarity-grid">
        ${factors
          .map(
            (f) => `
          <div class="similarity-cell">
            <strong>${escapeHtml(f.label)}: ${f.data ? f.data.score : 0}%</strong>
            <div class="field-hint">${
              f.data && f.data.details && f.data.details.length
                ? escapeHtml(f.data.details[0])
                : "—"
            }</div>
          </div>
        `
          )
          .join("")}
      </div>
    </details>
  `;
}

function renderResultCard(item, idx, isWinner) {
  const statusMeta = STATUS_LABELS[item.status] || {
    text: item.status,
    dot: "warn",
  };
  const completenessText = COMPLETENESS_LABELS[item.completeness] || item.completeness;
  const ownBadge = item.is_own_company
    ? '<span class="badge-soft badge-own">Ваша компания</span>'
    : "";
  const typeLabel = !item.is_locked ? PROVIDER_TYPE_LABELS[item.provider_type] : null;
  const typeBadge = typeLabel
    ? `<span class="badge-soft">${escapeHtml(typeLabel)}</span>`
    : "";
  const simBadge =
    typeof item.similarity_score === "number"
      ? `<span class="badge-soft tabular">Сходство: ${item.similarity_score}%</span>`
      : "";

  if (item.is_locked) {
    return `
      <article class="result-card result-card--locked">
        <div class="result-card-top">
          <div class="result-head-group">
            <h3 class="result-provider">${escapeHtml(item.provider_name)} ${simBadge}</h3>
            <div class="status-line">
              <span class="status-dot status-dot--${statusMeta.dot}" aria-hidden="true"></span>
              <span>${escapeHtml(statusMeta.text)} · ${escapeHtml(completenessText)}</span>
            </div>
          </div>
          <div>
            <div class="result-price result-price--empty">Скрыто до оплаты</div>
          </div>
        </div>
        <div class="locked-mask-note">
          Цена, детальная смета доплат, состав работ и пояснения скрыты на сервере до разблокировки отчёта.
        </div>
      </article>
    `;
  }

  const priceHtml =
    item.total_estimated_price !== null && item.total_estimated_price !== undefined
      ? `<div class="result-price tabular">${formatMoney(item.total_estimated_price)} ₽</div>`
      : `<div class="result-price result-price--empty">Расчёт невозможен</div>`;

  const adjustedHtml =
    item.adjusted_price !== null &&
    item.adjusted_price !== undefined &&
    (item.adjustment_note || item.adjusted_price !== item.total_estimated_price)
      ? `
        <div class="adjusted-price-box tabular">
          <strong>Приведённая цена: ~${formatMoney(item.adjusted_price)} ₽</strong>
          ${
            item.price_range_min !== null && item.price_range_max !== null
              ? `<span>(коридор ${formatMoney(item.price_range_min)}–${formatMoney(item.price_range_max)} ₽)</span>`
              : ""
          }
          ${item.adjustment_note ? `<div class="field-hint">${escapeHtml(item.adjustment_note)}</div>` : ""}
        </div>
      `
      : "";

  const breakdownHtml =
    item.price_breakdown && item.price_breakdown.length
      ? `
      <div class="breakdown-list" aria-label="Детализация стоимости">
        ${item.price_breakdown
          .map(
            (row) => `
          <div class="breakdown-row">
            <span class="breakdown-row-label">${escapeHtml(formatUnitsInText(row.label))}</span>
            <span class="breakdown-row-amount tabular">${formatMoney(row.amount)} ₽</span>
          </div>
        `
          )
          .join("")}
      </div>
    `
      : "";

  const diffContent =
    item.differences && item.differences.length
      ? `<ul>${item.differences.map((d) => `<li>${escapeHtml(formatUnitsInText(d))}</li>`).join("")}</ul>`
      : `<p class="explain-ok">Существенных расхождений со сценарием нет.</p>`;

  const hasMissing = item.missing_info && item.missing_info.length > 0;
  const missingContent = hasMissing
    ? `<ul>${item.missing_info.map((m) => `<li>${escapeHtml(m)}</li>`).join("")}</ul>
       <button type="button" class="btn btn-secondary btn-sm copy-questions-btn" data-copy-idx="${idx}">
         Скопировать вопросы подрядчику
       </button>`
    : `<p class="explain-ok">Все ключевые сведения указаны.</p>`;

  return `
    <article class="result-card${isWinner ? " result-card--winner" : ""}">
      <div class="result-card-top">
        <div class="result-head-group">
          <h3 class="result-provider">${escapeHtml(item.provider_name)} ${ownBadge} ${typeBadge} ${simBadge}</h3>
          <div class="status-line">
            <span class="status-dot status-dot--${statusMeta.dot}" aria-hidden="true"></span>
            <span>${escapeHtml(statusMeta.text)} · ${escapeHtml(completenessText)}</span>
          </div>
        </div>
        <div>
          ${priceHtml}
        </div>
      </div>
      ${breakdownHtml}
      ${adjustedHtml}
      ${renderSimilarityBreakdown(item.similarity_breakdown)}
      <div class="explain-grid">
        <div class="explain-box">
          <h4>Чем обусловлены отличия</h4>
          ${diffContent}
        </div>
        <div class="explain-box">
          <h4>Чего не хватает</h4>
          ${missingContent}
        </div>
      </div>
    </article>
  `;
}

function attachCopyHandlers(container, results, scenarioTitle) {
  container.querySelectorAll("[data-copy-idx]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.getAttribute("data-copy-idx"));
      const item = results[idx];
      if (!item || !item.missing_info || !item.missing_info.length) return;
      const lines = item.missing_info.map((m) => `— ${m}`).join("\n");
      const message =
        `Здравствуйте! Чтобы корректно оценить ваше предложение для задачи «${scenarioTitle}», уточните, пожалуйста:\n${lines}`;
      copyQuestionsText(message, btn);
    });
  });
}

export function renderComparisonResults(
  container,
  results,
  scenarioTitle = "задачу",
  { onDemo } = {}
) {
  if (!results || !results.length) {
    container.innerHTML = `
      <div class="empty-state">
        <h3>Готово к сравнению</h3>
        <p>Заполните услугу, город и ключевые работы выше и нажмите «Сравнить с рынком».</p>
        ${
          onDemo
            ? '<div style="margin-top: 16px"><button type="button" id="btn-empty-demo" class="btn btn-secondary btn-sm">Посмотреть на примере готового отчёта</button></div>'
            : ""
        }
      </div>
    `;
    const demoBtn = container.querySelector("#btn-empty-demo");
    if (demoBtn && onDemo) {
      demoBtn.addEventListener("click", onDemo);
    }
    return;
  }

  container.innerHTML = results
    .map((item, idx) => {
      const isWinner =
        idx === 0 &&
        !item.is_locked &&
        item.status !== "not_comparable" &&
        item.total_estimated_price !== null;
      return renderResultCard(item, idx, isWinner);
    })
    .join("");

  attachCopyHandlers(container, results, scenarioTitle);
}

export function renderComparisonReport(
  container,
  report,
  scenarioTitle = "задачу",
  { onUnlock, segmentFilter = "all", onFilterChange } = {}
) {
  if (!report || !report.results || !report.results.length) {
    renderComparisonResults(container, [], scenarioTitle);
    return;
  }

  let summaryHtml = "";
  let filterHtml = "";
  if (report.is_unlocked && (report.market_summary || report.own_positioning || report.price_recommendation)) {
    const ms = report.market_summary;
    const pos = report.own_positioning;
    const rec = report.price_recommendation;
    const segEntries =
      ms && ms.segments
        ? Object.entries(ms.segments).filter(([, s]) => s && s.total_offers_found > 0)
        : [];
    const segmentsHtml = segEntries.length
      ? `
        <div class="segment-breakdown-list">
          ${segEntries
            .map(([key, seg]) => {
              const title = PROVIDER_TYPE_LABELS[key] || key;
              const rangeText =
                seg.min_price !== null && seg.max_price !== null
                  ? `${formatMoney(seg.min_price)}–${formatMoney(seg.max_price)} ₽ (медиана ${formatMoney(seg.median_price)} ₽)`
                  : "нет расчётной цены";
              return `<div class="segment-row tabular"><span>${escapeHtml(title)} (${seg.total_offers_found})</span><strong>${rangeText}</strong></div>`;
            })
            .join("")}
        </div>
      `
      : "";

    summaryHtml = `
      <div class="report-summary-grid">
        ${
          rec
            ? `
          <div class="report-summary-card report-summary-card--accent">
            <h3>Рекомендуемая цена</h3>
            <p style="margin: 0 0 8px; font-size: 0.875rem;">${escapeHtml(rec.strategy_text)}</p>
            <div class="report-kpi-row tabular">
              <div class="report-kpi"><span>Минимум</span><strong>${rec.recommended_min !== null ? `${formatMoney(rec.recommended_min)} ₽` : "—"}</strong></div>
              <div class="report-kpi"><span>Оптимум</span><strong>${rec.recommended_optimal !== null ? `${formatMoney(rec.recommended_optimal)} ₽` : "—"}</strong></div>
              <div class="report-kpi"><span>Максимум</span><strong>${rec.recommended_max !== null ? `${formatMoney(rec.recommended_max)} ₽` : "—"}</strong></div>
            </div>
          </div>
        `
            : ""
        }
        ${
          ms
            ? `
          <div class="report-summary-card">
            <h3>Сводка по рынку</h3>
            <div class="field-hint">Сопоставимо: ${ms.comparable_offers_count} из ${ms.total_offers_found} конкурентов</div>
            <div class="report-kpi-row tabular">
              <div class="report-kpi"><span>Минимум</span><strong>${ms.min_price !== null ? `${formatMoney(ms.min_price)} ₽` : "—"}</strong></div>
              <div class="report-kpi"><span>Медиана</span><strong>${ms.median_price !== null ? `${formatMoney(ms.median_price)} ₽` : "—"}</strong></div>
              <div class="report-kpi"><span>Максимум</span><strong>${ms.max_price !== null ? `${formatMoney(ms.max_price)} ₽` : "—"}</strong></div>
            </div>
            ${segmentsHtml}
          </div>
        `
            : ""
        }
        ${
          pos
            ? `
          <div class="report-summary-card">
            <h3>Позиционирование вашей компании</h3>
            <p style="margin: 0 0 6px; font-size: 0.875rem;">${escapeHtml(pos.summary_text)}</p>
            ${
              pos.segment_summary_text
                ? `<p class="field-hint" style="margin: 0 0 8px;">${escapeHtml(pos.segment_summary_text)}</p>`
                : ""
            }
            <div class="report-kpi-row tabular">
              <div class="report-kpi"><span>Ваша цена</span><strong>${pos.own_price !== null ? `${formatMoney(pos.own_price)} ₽` : "—"}</strong></div>
              <div class="report-kpi"><span>Место</span><strong>${pos.price_rank ? `${pos.price_rank} из ${pos.ranked_offers_count}` : "—"}</strong></div>
              <div class="report-kpi"><span>Сходство</span><strong>${pos.own_similarity_score}%</strong></div>
            </div>
          </div>
        `
            : ""
        }
      </div>
    `;

    if (segEntries.length > 0) {
      const compCount = report.results.filter((r) => r.provider_type === "company").length;
      const privCount = report.results.filter((r) => r.provider_type === "private").length;
      filterHtml = `
        <div class="filter-pills" role="group" aria-label="Фильтр по типу исполнителя">
          <button type="button" class="btn btn-sm ${segmentFilter === "all" ? "btn-primary" : "btn-secondary"}" data-seg-filter="all">Все (${report.results.length})</button>
          <button type="button" class="btn btn-sm ${segmentFilter === "company" ? "btn-primary" : "btn-secondary"}" data-seg-filter="company">Компании (${compCount})</button>
          <button type="button" class="btn btn-sm ${segmentFilter === "private" ? "btn-primary" : "btn-secondary"}" data-seg-filter="private">Частные исполнители (${privCount})</button>
        </div>
      `;
    }
  } else if (!report.is_unlocked) {
    summaryHtml = `
      <div class="unlock-banner">
        <div>
          <strong>Доступен полный отчёт за 1 кредит</strong>
          <p>
            Откроет сводку по рынку (включая разделение на компании и частников), позиционирование вашей компании
            ${
              report.locked_competitors_count > 0
                ? `и ещё ${report.locked_competitors_count} скрытых конкурентов.`
                : "и полный разбор всех конкурентов."
            }
          </p>
        </div>
        <button type="button" id="btn-unlock-report" class="btn btn-primary">
          Открыть полный отчёт (1 кредит)
        </button>
      </div>
    `;
  }

  const visibleResults =
    report.is_unlocked && segmentFilter !== "all"
      ? report.results.filter(
          (item) => item.is_own_company || item.provider_type === segmentFilter
        )
      : report.results;

  const cardsHtml = visibleResults.length
    ? visibleResults
        .map((item, idx) => {
          const isWinner =
            idx === 0 &&
            !item.is_locked &&
            item.status !== "not_comparable" &&
            item.total_estimated_price !== null;
          return renderResultCard(item, idx, isWinner);
        })
        .join("")
    : '<p class="field-hint">В выбранном сегменте пока нет предложений.</p>';

  const unpricedList = report.is_unlocked && Array.isArray(report.unpriced_results) ? report.unpriced_results : [];
  const unpricedHtml = unpricedList.length
    ? `
      <details class="extra-details unpriced-drawer">
        <summary>
          <span>Исполнители без публичной цены («по договорённости»): ${unpricedList.length}</span>
          <span class="field-hint">Не участвуют в расчёте рыночной медианы</span>
        </summary>
        <div class="unpriced-list">
          ${unpricedList
            .map(
              (u) => `
            <div class="unpriced-row">
              <strong>${escapeHtml(u.provider_name)}</strong>
              <span class="field-hint">Сходство ${u.similarity_score}% · ${escapeHtml(u.missing_info && u.missing_info[0] ? u.missing_info[0] : "цена не указана")}</span>
            </div>
          `
            )
            .join("")}
        </div>
      </details>
    `
    : "";

  container.innerHTML = summaryHtml + filterHtml + cardsHtml + unpricedHtml;
  attachCopyHandlers(container, visibleResults, scenarioTitle);

  const unlockBtn = container.querySelector("#btn-unlock-report");
  if (unlockBtn && onUnlock) {
    unlockBtn.addEventListener("click", () => onUnlock(unlockBtn));
  }

  container.querySelectorAll("[data-seg-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const nextFilter = btn.getAttribute("data-seg-filter") || "all";
      if (onFilterChange) {
        onFilterChange(nextFilter);
      }
    });
  });
}
