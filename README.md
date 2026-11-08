# Claude Financial Skill — персональный финансовый аналитик

Отдайте ИИ свои банковские выписки — и получите разбор как от консультанта: куда уходят деньги,
что с этим делать и сколько это даст в рублях за год. Плюс отчёт с графиками.

Автор — Алик Завалишев, Telegram-канал [@zavalishevs](https://t.me/zavalishevs). Бесплатно.

## Два способа

### 1. Промпты — для ChatGPT и Claude в браузере
- [Промпт 1 — разбор выписки](prompts/prompt-1-razbor.md) ([PDF](prompts/prompt-1-razbor.pdf))
- [Промпт 2 — конкретные предложения под ваши траты](prompts/prompt-2-predlozheniya.md) ([PDF](prompts/prompt-2-predlozheniya.pdf)) — с включённым веб-поиском

### 2. Скилл для Claude Code — `personal-finance-analyst`
Сам читает выписки, сверяет итоги с шапкой, отделяет переводы себе и вклады от настоящих трат,
находит частые места, подписки, мелкие утечки, деньги без процентов и траты под налоговый вычет,
ищет актуальные накопительные счета и кешбэк, собирает `report.html` с графиками.

```bash
git clone https://github.com/zavalishev/claude-financial-skill.git
mkdir -p ~/.claude/skills && cp -r claude-financial-skill/personal-finance-analyst ~/.claude/skills/
```
Нужен Python 3 и `pdftotext` (`brew install poppler` на Mac, `sudo apt install poppler-utils` на Linux).

Дальше в Claude Code:
> Разбери мои выписки из ~/Downloads

Подробно — в [personal-finance-analyst/README.md](personal-finance-analyst/README.md).

## Приватность
Скилл считает всё на вашем компьютере, выписки никуда не отправляются. Перед использованием
промптов в браузере уберите из выписок номера карт и счетов, ФИО и имена людей в переводах.

## Важно
Это инструмент для самостоятельного разбора, а не финансовая, налоговая или инвестиционная рекомендация.
Ставки и правила вычетов — на ноябрь 2026 года; сверяйте их на сайтах банков, ЦБ и ФНС.

Чтение PDF проверено на выписках Сбера; CSV и Excel подходят для любого банка. Правила категорий
можно дополнять в `personal-finance-analyst/references/category_rules.json` — пул-реквесты приветствуются.

Лицензия — [MIT](LICENSE).
