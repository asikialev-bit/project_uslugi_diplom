const THEME_KEY = "servicematch-theme";

function getSystemTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function applyTheme(choice) {
  const root = document.documentElement;
  if (choice === "light" || choice === "dark") {
    root.setAttribute("data-theme", choice);
  } else {
    root.removeAttribute("data-theme");
  }
  updateThemeButton(choice);
}

function updateThemeButton(choice) {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  const effective = choice === "light" || choice === "dark" ? choice : getSystemTheme();
  const label = effective === "dark" ? "Тёмная тема" : "Светлая тема";
  btn.setAttribute("aria-label", `Переключить тему (сейчас: ${label})`);
  btn.setAttribute("title", `${label} — нажмите, чтобы переключить`);

  const sunIcon = btn.querySelector("[data-icon-sun]");
  const moonIcon = btn.querySelector("[data-icon-moon]");
  if (sunIcon && moonIcon) {
    sunIcon.style.display = effective === "dark" ? "block" : "none";
    moonIcon.style.display = effective === "dark" ? "none" : "block";
  }
}

export function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  applyTheme(saved);

  const btn = document.getElementById("theme-toggle");
  if (btn) {
    btn.addEventListener("click", () => {
      const currentAttr = document.documentElement.getAttribute("data-theme");
      const effective = currentAttr || getSystemTheme();
      const next = effective === "dark" ? "light" : "dark";
      localStorage.setItem(THEME_KEY, next);
      applyTheme(next);
    });
  }

  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (!localStorage.getItem(THEME_KEY)) {
        updateThemeButton(null);
      }
    });
}
