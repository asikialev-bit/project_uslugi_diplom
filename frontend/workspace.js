import {
  extractScenarioDetails,
  getCompanyProfile,
  getMe,
  getScenarioReport,
  listOffers,
  listScenarios,
  logoutUser,
  requestAuthCode,
  saveCompanyProfile,
  saveOffer,
  saveScenario,
  topupCredits,
  unlockScenarioReport,
  verifyAuthCode,
} from "/static/api.js";
import { renderComparisonReport, renderComparisonResults } from "/static/render.js";
import { initTheme } from "/static/theme.js";

initTheme();

const state = {
  scenarioId: null,
  offers: [],
  user: null,
  creditsBalance: 0,
  hasCompanyProfile: false,
  lastReport: null,
  lastScenarioTitle: "задачу",
  segmentFilter: "all",
};

const els = {
  alertBox: document.getElementById("workspace-alert"),

  accountPill: document.getElementById("account-pill"),
  accountPillText: document.getElementById("account-pill-text"),
  accountBackdrop: document.getElementById("account-modal-backdrop"),
  accountPanel: document.getElementById("account-panel"),
  btnCloseAccount: document.getElementById("btn-close-account"),
  btnGuestLoginLink: document.getElementById("btn-guest-login-link"),
  accountSummarySub: document.getElementById("account-summary-sub"),
  creditsBadge: document.getElementById("credits-badge"),
  authGuestView: document.getElementById("auth-guest-view"),
  authUserView: document.getElementById("auth-user-view"),
  authEmail: document.getElementById("auth-email"),
  authCodeField: document.getElementById("auth-code-field"),
  authCode: document.getElementById("auth-code"),
  btnRequestCode: document.getElementById("btn-request-code"),
  btnVerifyCode: document.getElementById("btn-verify-code"),
  accountUserEmail: document.getElementById("account-user-email"),
  accountBalance: document.getElementById("account-balance"),
  btnTopupDev: document.getElementById("btn-topup-dev"),
  btnLoadArchive: document.getElementById("btn-load-archive"),
  btnLogout: document.getElementById("btn-logout"),
  companyStatusHint: document.getElementById("company-status-hint"),
  companyProviderType: document.getElementById("company-provider-type"),
  companyProvider: document.getElementById("company-provider"),
  companyTitle: document.getElementById("company-title"),
  companyPrice: document.getElementById("company-price"),
  companyUnit: document.getElementById("company-unit"),
  companyCity: document.getElementById("company-city"),
  companyOnline: document.getElementById("company-online"),
  companyWorks: document.getElementById("company-works"),
  companyComponents: document.getElementById("company-components"),
  companyExclusions: document.getElementById("company-exclusions"),
  btnSaveCompany: document.getElementById("btn-save-company"),

  guestScenarioHint: document.getElementById("guest-scenario-hint"),
  authScenarioExtras: document.getElementById("auth-scenario-extras"),
  scenarioTitle: document.getElementById("scenario-title"),
  scenarioCity: document.getElementById("scenario-city"),
  scenarioOnline: document.getElementById("scenario-online"),
  scenarioWorks: document.getElementById("scenario-works"),
  scenarioFreeText: document.getElementById("scenario-free-text"),
  btnExtractScenario: document.getElementById("btn-extract-scenario"),
  scenarioDraftBadge: document.getElementById("scenario-draft-badge"),
  btnConfirmScenarioTags: document.getElementById("btn-confirm-scenario-tags"),
  scenarioVolume: document.getElementById("scenario-volume"),
  scenarioUnit: document.getElementById("scenario-unit"),
  scenarioComponents: document.getElementById("scenario-components"),
  scenarioConditions: document.getElementById("scenario-conditions"),
  scenarioConversions: document.getElementById("scenario-conversions"),
  scenarioExtraDetails: document.getElementById("scenario-extra-details"),

  resultsContainer: document.getElementById("comparison-results"),
  btnCompare: document.getElementById("btn-compare"),
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

function openAccountModal() {
  els.accountBackdrop.hidden = false;
  document.body.style.overflow = "hidden";
}

function closeAccountModal() {
  els.accountBackdrop.hidden = true;
  document.body.style.overflow = "";
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
  els.scenarioCity.value = scenario.city || "";
  els.scenarioOnline.checked = Boolean(scenario.is_online);
  els.scenarioWorks.value = (scenario.required_works || []).join(", ");
  els.scenarioVolume.value = scenario.volume || "1";
  els.scenarioUnit.value = scenario.pricing_unit || "fixed";
  els.scenarioComponents.value = (scenario.required_components || []).join(", ");
  els.scenarioConditions.value = (scenario.conditions || []).join(", ");
  els.scenarioConversions.value = formatConversions(scenario.unit_conversions);

  const hasExtra =
    (scenario.required_components && scenario.required_components.length > 0) ||
    (scenario.conditions && scenario.conditions.length > 0) ||
    (scenario.unit_conversions && Object.keys(scenario.unit_conversions).length > 0);
  if (els.scenarioExtraDetails) {
    els.scenarioExtraDetails.open = Boolean(hasExtra);
  }
}

function readScenarioFromForm() {
  if (!state.scenarioId) {
    state.scenarioId = `scen-${Date.now()}`;
  }
  const base = {
    id: state.scenarioId,
    title: els.scenarioTitle.value.trim() || "Сценарий заказа",
    city: els.scenarioCity.value.trim() || null,
    is_online: Boolean(els.scenarioOnline.checked),
    required_works: parseCsvList(els.scenarioWorks.value),
  };
  if (!state.user) {
    return {
      ...base,
      volume: "1",
      pricing_unit: "fixed",
      required_components: [],
      conditions: [],
      unit_conversions: {},
    };
  }
  return {
    ...base,
    volume: els.scenarioVolume.value.trim() || "1",
    pricing_unit: els.scenarioUnit.value.trim() || "fixed",
    required_components: parseCsvList(els.scenarioComponents.value),
    conditions: parseCsvList(els.scenarioConditions.value),
    unit_conversions: parseConversions(els.scenarioConversions.value),
  };
}

function renderAccountUi() {
  if (state.user) {
    els.accountPillText.textContent = `${state.user.email} · ${state.creditsBalance} кр.`;
    els.creditsBadge.textContent = `Баланс: ${state.creditsBalance} кр.`;
    els.accountSummarySub.textContent = `Вход выполнен: ${state.user.email}`;
    els.accountUserEmail.textContent = state.user.email;
    els.accountBalance.textContent = String(state.creditsBalance);
    els.companyStatusHint.textContent = state.hasCompanyProfile ? "Заполнено" : "Не заполнено";
    els.authGuestView.hidden = true;
    els.authUserView.hidden = false;
    els.guestScenarioHint.hidden = true;
    els.authScenarioExtras.hidden = false;
  } else {
    els.accountPillText.textContent = "Войти";
    els.creditsBadge.textContent = "Гость";
    els.accountSummarySub.textContent = "Войдите по одноразовому коду на email";
    els.authGuestView.hidden = false;
    els.authUserView.hidden = true;
    els.guestScenarioHint.hidden = false;
    els.authScenarioExtras.hidden = true;
  }
}

async function refreshAccountState() {
  try {
    const me = await getMe();
    state.user = me.user;
    state.creditsBalance = me.credits_balance ?? 0;
    state.hasCompanyProfile = Boolean(me.has_company_profile);
    if (state.hasCompanyProfile) {
      try {
        const company = await getCompanyProfile();
        els.companyProviderType.value = company.provider_type || "unknown";
        els.companyProvider.value = company.provider_name || "";
        els.companyTitle.value = company.service_title || "";
        els.companyPrice.value = company.base_price ?? "";
        els.companyUnit.value = company.pricing_unit || "";
        els.companyCity.value = company.city || "";
        els.companyOnline.checked = Boolean(company.is_online);
        els.companyWorks.value = (company.included_works || []).join(", ");
        els.companyComponents.value = (company.included_components || []).join(", ");
        els.companyExclusions.value = (company.exclusions_or_limits || []).join(", ");
      } catch {
        // Профиль ещё не создан
      }
    }
  } catch {
    state.user = null;
    state.creditsBalance = 0;
    state.hasCompanyProfile = false;
  }
  renderAccountUi();
}

function displayCurrentReport(report, scenarioTitle) {
  state.lastReport = report;
  state.lastScenarioTitle = scenarioTitle;
  renderComparisonReport(els.resultsContainer, report, scenarioTitle, {
    segmentFilter: state.segmentFilter,
    onUnlock: (btn) => handleUnlockReport(report.scenario_id, scenarioTitle, btn),
    onFilterChange: (nextFilter) => {
      state.segmentFilter = nextFilter;
      displayCurrentReport(state.lastReport, state.lastScenarioTitle);
    },
  });
}

async function handleUnlockReport(scenarioId, scenarioTitle, unlockBtn) {
  clearAlert();
  if (!state.user) {
    openAccountModal();
    showAlert("Войдите по email-коду, чтобы открыть полный отчёт.");
    return;
  }
  if (unlockBtn) {
    unlockBtn.disabled = true;
    unlockBtn.textContent = "Открываем...";
  }
  try {
    const report = await unlockScenarioReport(scenarioId);
    await refreshAccountState();
    state.segmentFilter = "all";
    displayCurrentReport(report, scenarioTitle);
    showAlert("Полный отчёт разблокирован.", "ok");
  } catch (err) {
    if (err.status === 402) {
      openAccountModal();
      showAlert("Недостаточно кредитов (требуется 1 кредит). Пополните баланс в кабинете.");
    } else {
      showAlert(err.message);
    }
  } finally {
    if (unlockBtn && document.body.contains(unlockBtn)) {
      unlockBtn.disabled = false;
      unlockBtn.textContent = "Открыть полный отчёт (1 кредит)";
    }
  }
}

async function runCompare(scrollToResults = false) {
  clearAlert();
  els.btnCompare.disabled = true;
  try {
    const scenario = readScenarioFromForm();
    await saveScenario(scenario);
    if (state.offers.length) {
      await Promise.all(state.offers.map((offer) => saveOffer(offer)));
    }
    const report = await getScenarioReport(scenario.id);
    if (!report.results.length && !report.own_result) {
      renderComparisonResults(els.resultsContainer, [], scenario.title, {
        onDemo: loadDemoReport,
      });
      showAlert(
        "В базе пока нет предложений рынка. Нажмите «Посмотреть на примере готового отчёта» ниже или заполните профиль компании."
      );
      return;
    }

    state.segmentFilter = "all";
    displayCurrentReport(report, scenario.title);
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

async function loadDemoReport() {
  clearAlert();
  state.scenarioId = null;
  applyScenarioToForm({
    title: "Срочная настройка под ключ",
    volume: "10",
    pricing_unit: "hour",
    city: null,
    is_online: false,
    required_works: ["аудит", "настройка"],
    required_components: ["материалы"],
    conditions: ["срочно"],
    unit_conversions: {},
  });

  state.offers = [
    {
      id: "demo-1",
      provider_name: "Специалист Андрей",
      provider_type: "private",
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
      provider_type: "company",
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
      provider_type: "company",
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
      provider_type: "company",
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

  await runCompare(true);
}

els.accountPill.addEventListener("click", openAccountModal);
els.btnGuestLoginLink.addEventListener("click", openAccountModal);
els.btnCloseAccount.addEventListener("click", closeAccountModal);
els.accountBackdrop.addEventListener("click", (event) => {
  if (event.target === els.accountBackdrop) {
    closeAccountModal();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !els.accountBackdrop.hidden) {
    closeAccountModal();
  }
});

els.btnRequestCode.addEventListener("click", async () => {
  clearAlert();
  const email = els.authEmail.value.trim();
  if (!email) {
    showAlert("Введите email для получения одноразового кода.");
    return;
  }
  els.btnRequestCode.disabled = true;
  try {
    await requestAuthCode(email);
    els.authCodeField.hidden = false;
    els.btnVerifyCode.hidden = false;
    showAlert("Одноразовый код отправлен (в dev-режиме — смотрите консоль сервера).", "ok");
  } catch (err) {
    showAlert(err.message);
  } finally {
    els.btnRequestCode.disabled = false;
  }
});

els.btnVerifyCode.addEventListener("click", async () => {
  clearAlert();
  const email = els.authEmail.value.trim();
  const code = els.authCode.value.trim();
  if (!email || !code) {
    showAlert("Введите email и 6-значный код.");
    return;
  }
  els.btnVerifyCode.disabled = true;
  try {
    await verifyAuthCode(email, code);
    els.authCode.value = "";
    await refreshAccountState();
    showAlert("Вы успешно вошли в систему.", "ok");
  } catch (err) {
    showAlert(err.message);
  } finally {
    els.btnVerifyCode.disabled = false;
  }
});

els.btnLogout.addEventListener("click", async () => {
  clearAlert();
  try {
    await logoutUser();
    await refreshAccountState();
    closeAccountModal();
    showAlert("Вы вышли из аккаунта.", "ok");
  } catch (err) {
    showAlert(err.message);
  }
});

els.btnTopupDev.addEventListener("click", async () => {
  clearAlert();
  els.btnTopupDev.disabled = true;
  try {
    const res = await topupCredits(1);
    state.creditsBalance = res.balance;
    renderAccountUi();
    showAlert(`Начислен 1 тестовый кредит. Баланс: ${res.balance} кр.`, "ok");
  } catch (err) {
    showAlert(err.message);
  } finally {
    els.btnTopupDev.disabled = false;
  }
});

els.btnLoadArchive.addEventListener("click", async () => {
  clearAlert();
  els.btnLoadArchive.disabled = true;
  try {
    const [scenarios, offers] = await Promise.all([listScenarios(), listOffers()]);
    if (!scenarios.length && !offers.length) {
      showAlert("В архиве пока пусто.");
      return;
    }
    if (scenarios.length) {
      const latestScenario = scenarios[scenarios.length - 1];
      state.scenarioId = latestScenario.id;
      applyScenarioToForm(latestScenario);
    }
    state.offers = offers;
    closeAccountModal();
    await runCompare(true);
  } catch (err) {
    showAlert(err.message);
  } finally {
    els.btnLoadArchive.disabled = false;
  }
});

els.btnSaveCompany.addEventListener("click", async () => {
  clearAlert();
  const provider = els.companyProvider.value.trim();
  const title = els.companyTitle.value.trim();
  if (!provider || !title) {
    showAlert("Укажите название вашей компании и услуги.");
    return;
  }
  els.btnSaveCompany.disabled = true;
  try {
    await saveCompanyProfile({
      id: "own",
      provider_name: provider,
      provider_type: els.companyProviderType.value || "unknown",
      service_title: title,
      base_price: els.companyPrice.value.trim() || null,
      pricing_unit: els.companyUnit.value.trim() || null,
      city: els.companyCity.value.trim() || null,
      is_online: Boolean(els.companyOnline.checked),
      included_works: parseCsvList(els.companyWorks.value),
      included_components: parseCsvList(els.companyComponents.value),
      exclusions_or_limits: parseCsvList(els.companyExclusions.value),
    });
    state.hasCompanyProfile = true;
    renderAccountUi();
    showAlert("Профиль вашей компании сохранён и будет учитываться в сравнениях.", "ok");
  } catch (err) {
    showAlert(err.message);
  } finally {
    els.btnSaveCompany.disabled = false;
  }
});

els.btnExtractScenario.addEventListener("click", async () => {
  clearAlert();
  const rawText = els.scenarioFreeText.value.trim();
  if (!rawText) {
    showAlert("Опишите задачу своими словами перед разбором через LLM.");
    return;
  }
  els.btnExtractScenario.disabled = true;
  els.btnExtractScenario.textContent = "Разбираем...";
  try {
    const draft = await extractScenarioDetails(rawText, els.scenarioTitle.value.trim() || null);
    els.scenarioWorks.value = (draft.required_works || []).join(", ");
    els.scenarioComponents.value = (draft.required_components || []).join(", ");
    els.scenarioConditions.value = (draft.conditions || []).join(", ");
    els.scenarioExtraDetails.open = true;
    els.scenarioDraftBadge.hidden = !draft.needs_confirmation;
    showAlert("Теги извлечены. Проверьте их и нажмите «Подтвердить теги».", "ok");
  } catch (err) {
    if (err.status === 401) {
      openAccountModal();
      showAlert("Войдите по email-коду, чтобы использовать LLM-разбор описания.");
    } else {
      showAlert(err.message);
    }
  } finally {
    els.btnExtractScenario.disabled = false;
    els.btnExtractScenario.textContent = "Разобрать в теги (LLM)";
  }
});

els.btnConfirmScenarioTags.addEventListener("click", () => {
  els.scenarioDraftBadge.hidden = true;
  showAlert("Теги сценария подтверждены.", "ok");
});

els.btnCompare.addEventListener("click", () => runCompare(true));

renderComparisonResults(els.resultsContainer, [], "задачу", {
  onDemo: loadDemoReport,
});
refreshAccountState();
