const AVAILABLE_LANGS = {
    zh: "中文",
    en: "English",
    ja:'日本語',
    vi: "Tiếng Việt"
};

const DEFAULT_LANG = "zh";
const LANG_STORAGE_KEY = "kano_lang";
let currentLang = DEFAULT_LANG;
let translations = {};

function detectBrowserLang() {
    const lang = navigator.language || navigator.userLanguage;
    const shortLang = lang.slice(0, 2);
    return AVAILABLE_LANGS[shortLang] ? shortLang : DEFAULT_LANG;
}

async function loadLanguage(lang) {
    try {
        const res = await fetch(`/lang/${lang}.json`);
        translations = await res.json();
        currentLang = lang;
        localStorage.setItem(LANG_STORAGE_KEY, lang);
        applyTranslations();
        updateSelectValue(lang);
    } catch (e) {
        console.error(`Failed to load language: ${lang}`, e);
    }
}

function applyTranslations() {
    document.querySelectorAll("[data-i18n]").forEach(el => {
        const key = el.getAttribute("data-i18n");
        if (translations[key]) {
            el.textContent = translations[key];
        }
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
        const key = el.getAttribute("data-i18n-placeholder");
        if (translations[key]) {
            el.placeholder = translations[key];
        }
    });
}

function createLanguageSelector() {
    const selector = document.querySelector("#LANG");

    Object.entries(AVAILABLE_LANGS).forEach(([key, label]) => {
        const option = document.createElement("option");
        option.value = key;
        option.textContent = label;
        selector.appendChild(option);
    });

    selector.addEventListener("change", (e) => {
        const selectedLang = e.target.value;
        loadLanguage(selectedLang);
    });
}

function updateSelectValue(lang) {
    const selector = document.querySelector("#LANG");
    selector.value = lang;
}


function t(key, fallback = "") {
    return translations[key] || fallback || key;
}

// 初始化
(function initI18n() {
    createLanguageSelector();
    const savedLang = localStorage.getItem(LANG_STORAGE_KEY);
    const langToLoad = savedLang || detectBrowserLang();
    loadLanguage(langToLoad);
})();
