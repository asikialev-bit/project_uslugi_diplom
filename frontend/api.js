async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }

  if (!response.ok) {
    const detail = data && data.detail ? data.detail : `Ошибка HTTP ${response.status}`;
    const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    error.status = response.status;
    throw error;
  }

  return data;
}

export function compareDirect(scenario, offers) {
  return requestJson("/compare", {
    method: "POST",
    body: JSON.stringify({ scenario, offers }),
  });
}

export function extractOfferFromText(rawText, providerName = null) {
  const body = { raw_text: rawText };
  if (providerName && providerName.trim()) {
    body.provider_name = providerName.trim();
  }
  return requestJson("/offers/extract", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function saveScenario(scenario) {
  return requestJson("/scenarios", {
    method: "POST",
    body: JSON.stringify(scenario),
  });
}

export function saveOffer(offer) {
  return requestJson("/offers", {
    method: "POST",
    body: JSON.stringify(offer),
  });
}

export function listScenarios() {
  return requestJson("/scenarios");
}

export function listOffers() {
  return requestJson("/offers");
}

export function requestAuthCode(email) {
  return requestJson("/auth/request-code", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function verifyAuthCode(email, code) {
  return requestJson("/auth/verify-code", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  });
}

export function logoutUser() {
  return requestJson("/auth/logout", {
    method: "POST",
  });
}

export function getMe() {
  return requestJson("/me");
}

export function getAccountHistory() {
  return requestJson("/me/history");
}

export function getCompanyProfile() {
  return requestJson("/me/company");
}

export function saveCompanyProfile(offer) {
  return requestJson("/me/company", {
    method: "PUT",
    body: JSON.stringify(offer),
  });
}

export function topupCredits(amount = 1) {
  return requestJson("/credits/topup", {
    method: "POST",
    body: JSON.stringify({ amount }),
  });
}

export function extractScenarioDetails(rawText, serviceTitle = null) {
  const body = { raw_text: rawText };
  if (serviceTitle && serviceTitle.trim()) {
    body.service_title = serviceTitle.trim();
  }
  return requestJson("/scenarios/extract-details", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getScenarioReport(scenarioId) {
  return requestJson(`/scenarios/${encodeURIComponent(scenarioId)}/report`);
}

export function unlockScenarioReport(scenarioId) {
  return requestJson(`/scenarios/${encodeURIComponent(scenarioId)}/unlock`, {
    method: "POST",
  });
}
