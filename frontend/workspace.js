import {
  compareDirect,
  extractOfferFromText,
  listOffers,
  listScenarios,
  saveOffer,
  saveScenario,
} from "/static/api.js";
import { renderComparisonResults, renderOffersList } from "/static/render.js";
import { initTheme } from "/static/theme.js";

initTheme();

const state = {
  offers: [],
  manualSurcharges: [],
  editingIndex: null,
};

const els = {
  alertBox: document.getElementById("workspace-alert"),
  scenarioTitle: document.getElementById("scenario-title"),
  scenarioVolume: document.getElementById("scenario-volume"),
  scenarioUnit: document.getElementById("scenario-unit"),
  scenarioWorks: document.getElementById("scenario-works"),
  scenarioComponents: document.getElementById("scenario-components"),
  scenarioConditions: document.getElementById("scenario-conditions"),
  scenarioConversions: document.getElementById("scenario-conversions"),

  tabManual: document.getElementById("tab-manual"),
  tabLlm: document.getElementById("tab-llm"),
  panelManual: document.getElementById("panel-manual"),
  panelLlm: document.getElementById("panel-llm"),

  llmText: document.getElementById("llm-raw-text"),
  llmProvider: document.getElementById("llm-provider"),
  btnExtractLlm: document.getElementById("btn-extract-llm"),

  offerProvider: document.getElementById("offer-provider"),
  offerTitle: document.getElementById("offer-title"),
  offerPrice: document.getElementById("offer-price"),
  offerUnit: document.getElementById("offer-unit"),
  offerWorks: document.getElementById("offer-works"),
  offerComponents: document.getElementById("offer-components"),
  offerExclusions: document.getElementById("offer-exclusions"),
  offerConditions: document.getElementById("offer-conditions"),
  offerMinVolume: document.getElementById("offer-min-volume"),
  offerMaxVolume: document.getElementById("offer-max-volume"),
  offerExtraDetails: document.getElementById("offer-extra-details"),
  surchargesContainer: document.getElementById("manual-surcharges"),
  btnAddSurcharge: document.getElementById("btn-add-surcharge"),
  btnAddOffer: document.getElementById("btn-add-offer"),
  btnCancelEdit: document.getElementById("btn-cancel-edit"),

  offersList: document.getElementById("offers-list"),
  resultsContainer: document.getElementById("comparison-results"),

  btnLoadDemo: document.getElementById("btn-load-demo"),
  btnLoadArchive: document.getElementById("btn-load-archive"),
  btnClearAll: document.getElementById("btn-clear-all"),
  btnCompare: document.getElementById("btn-compare"),
  btnSaveDb: document.getElementById("btn-save-db"),
};

function showAlert(message, kind = "error") {
  els.alertBox.hidden = false;
  els.alertBox.className = `alert ${kind === "ok" ? "alert-ok" : "alert-error"}`;
  els.alertBox.textContent = message;
}

function clearAlert() {
  els.alertBox.hidden = true;
  els.alertBox.textContent = "";
}

function parseCsvList(value) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseConversions(value) {
  const result = {};
  const parts = parseCsvList(value);
  for (const part of parts) {
    const [unit, factor] = part.split(":").map((s) => s.trim());
    if (unit && factor && !Number.isNaN(Number(factor))) {
      result[unit] = factor;
    }
  }
  return result;
}

function formatConversions(conversions) {
  if (!conversions || typeof conversions !== "object") return "";
  return Object.entries(conversions)
    .map(([unit, factor]) => `${unit}: ${factor}`)
    .join(", ");
}

function applyScenarioToForm(scenario) {
  els.scenarioTitle.value = scenario.title || "";
  els.scenarioVolume.value = scenario.volume || "1";
  els.scenarioUnit.value = scenario.pricing_unit || "fixed";
  els.scenarioWorks.value = (scenario.required_works || []).join(", ");
  els.scenarioComponents.value = (scenario.required_components || []).join(", ");
  els.scenarioConditions.value = (scenario.conditions || []).join(", ");
  els.scenarioConversions.value = formatConversions(scenario.unit_conversions);
}

function readScenarioFromForm() {
  return {
    id: "workspace-scenario",
    title: els.scenarioTitle.value.trim() || "Сценарий заказа",
    volume: els.scenarioVolume.value.trim() || "1",
    pricing_unit: els.scenarioUnit.value.trim() || "fixed",
    required_works: parseCsvList(els.scenarioWorks.value),
    required_components: parseCsvList(els.scenarioComponents.value),
    conditions: parseCsvList(els.scenarioConditions.value),
    unit_conversions: parseConversions(els.scenarioConversions.value),
  };
}

function renderManualSurcharges() {
  if (!state.manualSurcharges.length) {
    els.surchargesContainer.innerHTML = "";
    return;
  }

  els.surchargesContainer.innerHTML = state.manualSurcharges
    .map(
      (s, idx) => `
      <div class="surcharge-row" data-s-row="${idx}">
        <input class="input" type="text" placeholder="Название" value="${s.name}" data-s-field="name" />
        <input class="input" type="number" min="0" step="any" placeholder="Сумма" value="${s.amount}" data-s-field="amount" />
        <input class="input" type="text" placeholder="Ед. (fixed)" value="${s.unit}" data-s-field="unit" />
        <button type="button" class="btn btn-ghost btn-sm" data-s-del="${idx}">×</button>
        <label class="checkbox-row" style="grid-column: 1 / -1;">
          <input type="checkbox" ${s.is_mandatory ? "checked" : ""} data-s-field="is_mandatory" />
          Обязательная доплата (если снято — условная, активируется по условию ниже)
        </label>
        <input class="input" style="grid-column: 1 / -1;" type="text" placeholder="Условие (например: срочно)" value="${s.condition_description}" data-s-field="condition_description" />
      </div>
    `
    )
    .join("");

  els.surchargesContainer.querySelectorAll("[data-s-row]").forEach((row) => {
    const idx = Number(row.getAttribute("data-s-row"));
    row.querySelectorAll("[data-s-field]").forEach((input) => {
      const field = input.getAttribute("data-s-field");
      input.addEventListener("input", () => {
        if (field === "is_mandatory") {
          state.manualSurcharges[idx][field] = input.checked;
        } else {
          state.manualSurcharges[idx][field] = input.value;
        }
      });
      if (field === "is_mandatory") {
        input.addEventListener("change", () => {
          state.manualSurcharges[idx][field] = input.checked;
        });
      }
    });
  });

  els.surchargesContainer.querySelectorAll("[data-s-del]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.getAttribute("data-s-del"));
      state.manualSurcharges.splice(idx, 1);
      renderManualSurcharges();
    });
  });
}

function resetManualForm() {
  state.editingIndex = null;
  els.offerProvider.value = "";
  els.offerTitle.value = "";
  els.offerPrice.value = "";
  els.offerUnit.value = "";
  els.offerWorks.value = "";
  els.offerComponents.value = "";
  els.offerExclusions.value = "";
  els.offerConditions.value = "";
  els.offerMinVolume.value = "";
  els.offerMaxVolume.value = "";
  state.manualSurcharges = [];
  renderManualSurcharges();

  els.btnAddOffer.textContent = "Добавить предложение в список";
  els.btnCancelEdit.hidden = true;
}

function startEditingOffer(index) {
  const offer = state.offers[index];
  if (!offer) return;

  clearAlert();
  switchTab("manual");
  state.editingIndex = index;

  els.offerProvider.value = offer.provider_name || "";
  els.offerTitle.value = offer.service_title || "";
  els.offerPrice.value =
    offer.base_price !== null && offer.base_price !== undefined ? String(offer.base_price) : "";
  els.offerUnit.value = offer.pricing_unit || "";
  els.offerWorks.value = (offer.included_works || []).join(", ");
  els.offerComponents.value = (offer.included_components || []).join(", ");
  els.offerExclusions.value = (offer.exclusions_or_limits || []).join(", ");
  els.offerConditions.value = (offer.conditions || []).join(", ");
  els.offerMinVolume.value = offer.min_volume ? String(offer.min_volume) : "";
  els.offerMaxVolume.value = offer.max_volume ? String(offer.max_volume) : "";

  state.manualSurcharges = (offer.surcharges || []).map((s) => ({
    name: s.name || "",
    amount: s.amount !== undefined && s.amount !== null ? String(s.amount) : "0",
    unit: s.unit || "fixed",
    is_mandatory: Boolean(s.is_mandatory),
    condition_description: s.condition_description || "",
  }));
  renderManualSurcharges();

  const hasExtra =
    (offer.included_components && offer.included_components.length) ||
    (offer.exclusions_or_limits && offer.exclusions_or_limits.length) ||
    (offer.conditions && offer.conditions.length) ||
    offer.min_volume ||
    offer.max_volume ||
    state.manualSurcharges.length > 0;
  if (els.offerExtraDetails && hasExtra) {
    els.offerExtraDetails.open = true;
  }

  els.btnAddOffer.textContent = "Сохранить изменения";
  els.btnCancelEdit.hidden = false;

  const stepOffers = document.getElementById("step-offers");
  if (stepOffers) {
    stepOffers.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function refreshOffers() {
  renderOffersList(els.offersList, state.offers, {
    onEdit: (idx) => startEditingOffer(idx),
    onRemove: (idx) => {
      if (state.editingIndex === idx) {
        resetManualForm();
      } else if (state.editingIndex !== null && idx < state.editingIndex) {
        state.editingIndex -= 1;
      }
      state.offers.splice(idx, 1);
      refreshOffers();
    },
  });
}

function switchTab(mode) {
  const isManual = mode === "manual";
  els.tabManual.setAttribute("aria-selected", String(isManual));
  els.tabLlm.setAttribute("aria-selected", String(!isManual));
  els.panelManual.hidden = !isManual;
  els.panelLlm.hidden = isManual;
}

els.tabManual.addEventListener("click", () => switchTab("manual"));
els.tabLlm.addEventListener("click", () => switchTab("llm"));
els.btnCancelEdit.addEventListener("click", () => resetManualForm());

els.btnAddSurcharge.addEventListener("click", () => {
  state.manualSurcharges.push({
    name: "",
    amount: "0",
    unit: "fixed",
    is_mandatory: true,
    condition_description: "",
  });
  renderManualSurcharges();
});

els.btnAddOffer.addEventListener("click", () => {
  clearAlert();
  const provider = els.offerProvider.value.trim();
  const title = els.offerTitle.value.trim();
  if (!provider || !title) {
    showAlert("Укажите название исполнителя и название услуги.");
    return;
  }

  const surcharges = state.manualSurcharges
    .filter((s) => s.name.trim())
    .map((s) => ({
      name: s.name.trim(),
      amount: s.amount || "0",
      unit: s.unit.trim() || "fixed",
      is_mandatory: Boolean(s.is_mandatory),
      condition_description: s.condition_description.trim() || null,
    }));

  const existingId =
    state.editingIndex !== null && state.offers[state.editingIndex]
      ? state.offers[state.editingIndex].id
      : `offer-${Date.now()}`;

  const offer = {
    id: existingId,
    provider_name: provider,
    service_title: title,
    base_price: els.offerPrice.value.trim() ? els.offerPrice.value.trim() : null,
    pricing_unit: els.offerUnit.value.trim() ? els.offerUnit.value.trim() : null,
    included_works: parseCsvList(els.offerWorks.value),
    included_components: parseCsvList(els.offerComponents.value),
    exclusions_or_limits: parseCsvList(els.offerExclusions.value),
    conditions: parseCsvList(els.offerConditions.value),
    min_volume: els.offerMinVolume.value.trim() || null,
    max_volume: els.offerMaxVolume.value.trim() || null,
    surcharges,
  };

  if (state.editingIndex !== null) {
    state.offers[state.editingIndex] = offer;
    showAlert(`Предложение от «${offer.provider_name}» обновлено.`, "ok");
  } else {
    state.offers.push(offer);
  }

  resetManualForm();
  refreshOffers();
});

els.btnExtractLlm.addEventListener("click", async () => {
  clearAlert();
  const rawText = els.llmText.value.trim();
  if (!rawText) {
    showAlert("Вставьте текст предложения конкурента для извлечения.");
    return;
  }

  els.btnExtractLlm.disabled = true;
  els.btnExtractLlm.textContent = "Извлекаем...";
  try {
    const offer = await extractOfferFromText(rawText, els.llmProvider.value);
    state.offers.push(offer);
    refreshOffers();
    els.llmText.value = "";
    els.llmProvider.value = "";
    showAlert(
      `Предложение от «${offer.provider_name}» добавлено. При необходимости нажмите «Изменить» для правки.`,
      "ok"
    );
  } catch (err) {
    showAlert(err.message);
  } finally {
    els.btnExtractLlm.disabled = false;
    els.btnExtractLlm.textContent = "Извлечь через LLM";
  }
});

async function runCompare(scrollToResults = false) {
  clearAlert();
  if (!state.offers.length) {
    showAlert("Добавьте хотя бы одно предложение для сравнения.");
    return;
  }

  els.btnCompare.disabled = true;
  try {
    const scenario = readScenarioFromForm();
    const results = await compareDirect(scenario, state.offers);
    renderComparisonResults(els.resultsContainer, results, scenario.title);
    if (scrollToResults) {
      const resultsSection = document.getElementById("step-results");
      if (resultsSection) {
        resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  } catch (err) {
    showAlert(err.message);
  } finally {
    els.btnCompare.disabled = false;
  }
}

els.btnCompare.addEventListener("click", () => runCompare(true));

els.btnSaveDb.addEventListener("click", async () => {
  clearAlert();
  if (!state.offers.length) {
    showAlert("Добавьте предложения перед сохранением.");
    return;
  }
  els.btnSaveDb.disabled = true;
  try {
    const scenario = readScenarioFromForm();
    await saveScenario(scenario);
    for (const offer of state.offers) {
      await saveOffer(offer);
    }
    showAlert("Сценарий и предложения сохранены в архив SQLite.", "ok");
  } catch (err) {
    showAlert(err.message);
  } finally {
    els.btnSaveDb.disabled = false;
  }
});

els.btnLoadArchive.addEventListener("click", async () => {
  clearAlert();
  els.btnLoadArchive.disabled = true;
  try {
    const [scenarios, offers] = await Promise.all([listScenarios(), listOffers()]);
    if (!scenarios.length && !offers.length) {
      showAlert("В архиве пока пусто. Сначала нажмите «Сохранить в архив».");
      return;
    }

    resetManualForm();
    if (scenarios.length) {
      applyScenarioToForm(scenarios[scenarios.length - 1]);
    }
    if (offers.length) {
      state.offers = offers;
      refreshOffers();
      await runCompare(false);
    } else {
      state.offers = [];
      refreshOffers();
      renderComparisonResults(els.resultsContainer, []);
    }
    showAlert(
      `Загружено из архива: сценариев — ${scenarios.length ? 1 : 0}, предложений — ${offers.length}.`,
      "ok"
    );
  } catch (err) {
    showAlert(err.message);
  } finally {
    els.btnLoadArchive.disabled = false;
  }
});

els.btnLoadDemo.addEventListener("click", async () => {
  clearAlert();
  resetManualForm();
  applyScenarioToForm({
    title: "Срочная настройка под ключ",
    volume: "10",
    pricing_unit: "hour",
    required_works: ["аудит", "настройка"],
    required_components: ["материалы"],
    conditions: ["срочно"],
    unit_conversions: {},
  });

  state.offers = [
    {
      id: "demo-1",
      provider_name: "Специалист Андрей",
      service_title: "Настройка по ставке за час",
      base_price: "1000",
      pricing_unit: "час",
      included_works: ["аудит", "настройка"],
      included_components: ["материалы"],
      exclusions_or_limits: [],
      conditions: [],
      min_volume: "5",
      max_volume: null,
      surcharges: [
        {
          name: "Выезд специалиста",
          amount: "500",
          unit: "fixed",
          is_mandatory: true,
          condition_description: null,
        },
        {
          name: "Срочный запуск",
          amount: "1500",
          unit: "fixed",
          is_mandatory: false,
          condition_description: "срочно",
        },
      ],
    },
    {
      id: "demo-2",
      provider_name: "Студия «Квадрат»",
      service_title: "Пакет под ключ",
      base_price: "12000",
      pricing_unit: "fixed",
      included_works: ["аудит", "настройка"],
      included_components: ["материалы"],
      exclusions_or_limits: [],
      conditions: ["срочно"],
      surcharges: [],
    },
    {
      id: "demo-3",
      provider_name: "Мастерская «Профи»",
      service_title: "Индивидуальный расчёт",
      base_price: null,
      pricing_unit: null,
      included_works: ["аудит", "настройка"],
      included_components: [],
      exclusions_or_limits: [],
      conditions: [],
      surcharges: [],
    },
    {
      id: "demo-4",
      provider_name: "Агентство «Стартер»",
      service_title: "Базовый аудит",
      base_price: "900",
      pricing_unit: "hour",
      included_works: ["аудит"],
      included_components: [],
      exclusions_or_limits: ["настройка"],
      conditions: [],
      surcharges: [],
    },
  ];

  refreshOffers();
  await runCompare(true);
});

els.btnClearAll.addEventListener("click", () => {
  clearAlert();
  resetManualForm();
  state.offers = [];
  refreshOffers();
  renderComparisonResults(els.resultsContainer, []);
});

refreshOffers();
renderComparisonResults(els.resultsContainer, []);
