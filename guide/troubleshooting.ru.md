# Если что-то не так

[README](../README.ru.md) · [Установка](install.ru.md) · [Как пользоваться](usage.ru.md) · **Если что-то не так** · [English](troubleshooting.md)

| | |
|---|---|
| Бот молчит | `pult status` покажет службу и связь с Telegram; `pult restart`. Журнал — `~/Library/Logs/pult.log` (macOS), `~/.local/state/pult/pult.log` (Linux, Windows). |
| Linux: Пульт останавливается, когда выходишь | `sudo loginctl enable-linger $USER`. |
| VS Code: «Claude Code native binary not found at …» | Строка обёртки в настройках VS Code сломана или указывает на несуществующий файл: `pult status` напечатает правильную; потом Reload Window. |
| Нет сессий из VS Code | Хуки выключены: `pult hooks on`, затем Reload Window. |
| В журнале `409` | Обновления этого бота читает другая программа, например вторая копия Пульта. |
| Кнопок разрешений нет, а лента есть | Режим `auto` в Claude Code решает сам. Это нормально. |
| Сообщение в открытую вкладку ушло копией | Вкладка открыта до обёртки (поможет Reload Window) или только что обновилось расширение (Пульт написал об этом в «Общую»). |
| Другое | `pult report`, затем [заведи issue](https://github.com/pulthq/pult/issues/new/choose). |

**Несколько человек?** Нет: у одного Пульта один владелец. **Лишний расход?** Нет: Пульт тратит только то, что
тратят сами сессии; лимиты он узнаёт у Claude Code без запроса к модели.
