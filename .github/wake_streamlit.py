"""Разбудить сайт на Streamlit Cloud, если он «уснул» (бесплатный тариф усыпляет сайт без посетителей).

    python .github/wake_streamlit.py https://wastewise-kz.streamlit.app/

Открывает сайт в браузере без окна. Если вместо приложения экран «Zzzz» — нажимает кнопку
«Yes, get this app back up!» и ждёт, пока сайт загрузится. Обычный HTTP-запрос (curl) сайт не будит:
нужен настоящий браузер, поэтому Playwright.
"""
import sys

from playwright.sync_api import sync_playwright

WAKE_BUTTON = "Yes, get this app back up"


def main(url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(8_000)
        button = page.get_by_role("button", name=WAKE_BUTTON)
        if button.count():
            print("Сайт спал — бужу")
            button.first.click()
            page.wait_for_timeout(90_000)  # просыпается до минуты-двух: ставит пакеты и грузит модели
        else:
            print("Сайт не спал")
        still_asleep = page.get_by_role("button", name=WAKE_BUTTON).count() > 0
        browser.close()
    if still_asleep:
        print("❌ Сайт так и не проснулся")
        return 1
    print("✅ Сайт работает")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "https://wastewise-kz.streamlit.app/"))
