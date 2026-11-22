const SCENARIOS_DEMO = {
  showcase: {
    caption: "Как предложения выглядят в рекламе, если смотреть только на ставку",
    items: [
      {
        name: "Агентство «Стартер»",
        price: "900 ₽ / час",
        dot: "ok",
        status: "Самая низкая цена на витрине",
        note: "Кажется самым выгодным вариантом при беглом сравнении ценников.",
      },
      {
        name: "Специалист Андрей",
        price: "1 000 ₽ / час",
        dot: "ok",
        status: "Базовая ставка без доплат на виду",
        note: "Выезд, срочность и минимальный объём вынесены в сноску внизу.",
      },
      {
        name: "Студия «Квадрат»",
        price: "12 000 ₽",
        dot: "warn",
        status: "Фиксированный пакет под ключ",
        note: "Выглядит дороже других, потому что сразу названа полная сумма.",
      },
    ],
  },
  reality: {
    caption: "Смета под реальный заказ: 10 часов · с настройкой · срочно",
    items: [
      {
        name: "Специалист Андрей",
        price: "12 000 ₽",
        dot: "ok",
        status: "Подходит полностью · все условия учтены",
        note: "10 000 ₽ работа + 500 ₽ выезд + 1 500 ₽ за срочность. Прозрачная смета.",
      },
      {
        name: "Студия «Квадрат»",
        price: "12 000 ₽",
        dot: "warn",
        status: "Подходит с оговоркой · фикс за проект",
        note: "Итоговая цена та же, но при изменении объёма пересчёта не будет.",
      },
      {
        name: "Агентство «Стартер»",
        price: "Не подходит",
        dot: "err",
        status: "Не подходит под заказ · есть пробелы",
        note: "Ключевая настройка исключена из пакета; не указаны материалы и условия.",
      },
    ],
  },
};

function renderFanDeck(deckEl, captionEl, mode) {
  const data = SCENARIOS_DEMO[mode];
  if (!data) return;
  captionEl.textContent = data.caption;

  deckEl.innerHTML = data.items
    .map((item, idx) => {
      const dimmedClass = item.dot === "err" ? " is-dimmed" : "";
      return `
        <article class="fan-card${dimmedClass}" data-pos="${idx + 1}">
          <div class="fan-card-top">
            <span class="fan-card-name">${item.name}</span>
            <span class="fan-card-price">${item.price}</span>
          </div>
          <div class="status-line">
            <span class="status-dot status-dot--${item.dot}" aria-hidden="true"></span>
            <span>${item.status}</span>
          </div>
          <p class="fan-card-note">${item.note}</p>
        </article>
      `;
    })
    .join("");
}

export function initRealitySwitch() {
  const deckEl = document.getElementById("hero-fan-deck");
  const captionEl = document.getElementById("reality-caption");
  const buttons = document.querySelectorAll("[data-reality-mode]");
  if (!deckEl || !captionEl || !buttons.length) return;

  renderFanDeck(deckEl, captionEl, "reality");

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.getAttribute("data-reality-mode");
      buttons.forEach((b) => {
        b.setAttribute("aria-pressed", String(b === btn));
      });

      const update = () => renderFanDeck(deckEl, captionEl, mode);
      if (document.startViewTransition) {
        document.startViewTransition(update);
      } else {
        update();
      }
    });
  });
}

export function initCurtainAndReveals() {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const reveals = document.querySelectorAll(".reveal-on-scroll");

  if (reduced || !("IntersectionObserver" in window)) {
    reveals.forEach((el) => el.classList.add("is-visible"));
  } else {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.14 }
    );
    reveals.forEach((el) => observer.observe(el));
  }

  const hero = document.getElementById("hero-stage");
  if (!hero || reduced) return;

  let ticking = false;
  const updateHeroDepth = () => {
    ticking = false;
    if (window.innerWidth <= 960) {
      hero.style.transform = "";
      hero.style.opacity = "";
      return;
    }
    const maxScroll = Math.max(window.innerHeight * 0.85, 500);
    const progress = Math.min(Math.max(window.scrollY / maxScroll, 0), 1);
    const scale = 1 - progress * 0.035;
    const opacity = 1 - progress * 0.42;
    hero.style.transform = `scale(${scale.toFixed(4)})`;
    hero.style.opacity = opacity.toFixed(3);
  };

  window.addEventListener(
    "scroll",
    () => {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(updateHeroDepth);
      }
    },
    { passive: true }
  );
}
