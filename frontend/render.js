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
    const original = buttonEl.textContent;
    buttonEl.textContent = "Скопировано";
    window.setTimeout(() => {
      buttonEl.textContent = original;
    }, 1800);
  } catch {
    buttonEl.textContent = "Не удалось скопировать";
  }
}

export function renderComparisonResults(container, results, scenarioTitle = "задачу") {
  if (!results || !results.length) {
    container.innerHTML = `
      <div class="empty-state">
        <h3>Готово к сравнению</h3>
        <p>Когда добавите предложения на шаге 2 и нажмёте «Показать реальную стоимость», здесь появятся подробные сметы.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = results
    .map((item, idx) => {
      const statusMeta = STATUS_LABELS[item.status] || {
        text: item.status,
        dot: "warn",
      };
      const completenessText = COMPLETENESS_LABELS[item.completeness] || item.completeness;
      const isWinner =
        idx === 0 && item.status !== "not_comparable" && item.total_estimated_price !== null;

      const priceHtml =
        item.total_estimated_price !== null && item.total_estimated_price !== undefined
          ? `<div class="result-price tabular">${formatMoney(item.total_estimated_price)} ₽</div>`
          : `<div class="result-price result-price--empty">Расчёт невозможен</div>`;

      const breakdownHtml =
        item.price_breakdown && item.price_breakdown.length
          ? `
          <div class="breakdown-list" aria-label="Детализация стоимости">
            ${item.price_breakdown
              .map(
                (row) => `
              <div class="breakdown-row">
                <span class="breakdown-row-label">${escapeHtml(row.label)}</span>
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
          ? `<ul>${item.differences.map((d) => `<li>${escapeHtml(d)}</li>`).join("")}</ul>`
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
              <h3 class="result-provider">${escapeHtml(item.provider_name)}</h3>
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
    })
    .join("");

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
