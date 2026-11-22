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
