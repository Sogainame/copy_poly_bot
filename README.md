# Copy Poly Bot

Копитрейл-бот для Polymarket: следит за сделками одного кошелька в реалтайме и копирует их пропорционально.

## Архитектура

```
bot.py                  — главный entry point (демон, постоянно слушает)
analyze.py              — CLI отчёт по PnL и сравнению трейдер vs мы
config.yaml             — настройки (адрес, размер, фильтры, режим)
.env                    — секреты (Telegram, Polymarket keys)

src/
  config.py             — загрузка yaml + .env, валидация
  watcher.py            — polling Polymarket Data API + retry на 429
  filters.py            — фильтр по типу маркета (BTC 5m/15m и т.п.)
  copy_engine.py        — расчёт размера копии + DRY/LIVE логика
  storage.py            — запись JSONL + state
  gamma.py              — запросы к Gamma API (получение исхода окон)
  analyzer.py           — расчёт PnL по окнам
  telegram.py           — опциональные алерты

data/                   — генерируется автоматически
  trader_trades.jsonl   — ВСЕ сделки трейдера (даже отфильтрованные, для аналитики)
  our_copies.jsonl      — наши копии (только то что прошло фильтры)
  state.json            — seen_ids + copy_n + last_target
  bot.log               — человеко-читаемый лог
```

## Установка

```bash
git clone https://github.com/Sogainame/copy_poly_bot.git
cd copy_poly_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # отредактировать если нужны Telegram-алерты
```

## Конфиг

Открой `config.yaml`. Главные поля:

```yaml
target_wallet: "0xce25..."     # адрес которого копируем
bet_pct: 0.10                  # 10% от его сделки
bet_min: 1.0
bet_max: 10.0
filter_markets: [btc-5m, btc-15m]
poll_interval: 0.5             # сек между опросами
mode: dry                      # dry | live
```

### Смена трейдера

Поменяй `target_wallet` в `config.yaml` и перезапусти бота. seen_ids сохранятся (на всякий случай), но если хочешь полностью с нуля — удали `data/state.json` перед запуском.

### Доступные фильтры маркетов

- `btc-5m`, `btc-15m` — Bitcoin Up or Down 5/15-минутные
- `eth-5m`, `eth-15m` — Ethereum
- `sol-5m`, `sol-15m` — Solana
- `xrp-5m`, `xrp-15m` — XRP
- `doge-5m`, `doge-15m` — Dogecoin

## Запуск

### Постоянный мониторинг (демон):

```bash
python3 bot.py
```

Останавливается через Ctrl+C. Стейт сохраняется автоматически. При перезапуске продолжает с того же места.

Для постоянной работы рекомендуется `tmux` или `screen`:

```bash
tmux new -s copybot
python3 bot.py
# Ctrl+B затем D — детач (бот продолжит работать)
# tmux a -t copybot — присоединиться обратно
```

Или через systemd / supervisord для VPS.

### Анализ PnL:

```bash
python3 analyze.py
```

Покажет таблицу по каждому окну:
- сколько $ трейдер потратил на UP/DOWN
- сколько мы потратили
- кто победил
- наш PnL и ROI
- общий итог

## Логи

**`bot.log`** — текстовый лог (компактный, 1 строка на сделку):
```
[2026-05-25 11:30:51] COPY #1 Down @0.480 → 2.08sh $1.00 (он $13.44) | May 25, 12:30AM-12:45AM ET
```

**`trader_trades.jsonl`** — структурированные данные ВСЕХ сделок трейдера (даже отфильтрованных). Можно парсить для дополнительной аналитики.

**`our_copies.jsonl`** — наши копии. У каждой есть `parent_dedup_key` → можно точно сопоставить с сделкой в `trader_trades.jsonl`.

## Режимы

- **dry** — бот логирует что бы он купил, но реальных ордеров не делает. Безопасно для тестирования.
- **live** — реальные ордера. Требует `BUILDER_API_KEY`, `BUILDER_SECRET`, `BUILDER_PASSPHRASE` в `.env`. **Пока не реализовано** — будет добавлено после успешного DRY-тестирования.

## Дедупликация

Каждая сделка получает уникальный `dedup_key`:
- если есть `transactionHash` — используется он (самый надёжный)
- иначе fallback: `timestamp_asset_size_price_side`

seen_ids хранятся в `state.json` (последние 5000). При перезапуске бот не копирует уже виденные сделки.

## Минимизация задержки

- Polling 0.5 сек (24 запроса/мин — точно ниже rate limit'ов Polymarket)
- Retry с exponential backoff на HTTP 429 / 5xx
- `api_limit=20` (не 50) — быстрее приходит ответ
- WebSocket недоступен: market channel не возвращает wallet addresses, user channel требует API-ключи трейдера которых у нас нет
- Запуск ближе к US East снижает RTT (Vultr Newark / AWS us-east-1 = ~10ms vs Phuket = ~250ms)

## Roadmap

- [x] DRY mode с пропорциональным размером
- [x] Дублирующиеся фильтры (BUY, размер, маркеты)
- [x] Структурированные логи + state
- [x] Анализатор PnL
- [ ] LIVE mode через py-clob-client
- [ ] Auto-redeem резолвенных позиций через poly-web3
- [ ] Поддержка нескольких трейдеров одновременно
- [ ] Sell-on-90% для ускорения оборота капитала

## Известные ограничения

1. **Polymarket Data API имеет задержку 5-15 сек** относительно реального момента сделки. Минимизировать polling-интервалом нельзя — это задержка на стороне Polymarket.
2. **WebSocket market channel не содержит wallet addresses** → для копирования по адресу можно только polling.
3. **Дата в title маркета** содержит "May 25" даже если бот работает 26 мая — потому что Polymarket пишет дату START окна.
