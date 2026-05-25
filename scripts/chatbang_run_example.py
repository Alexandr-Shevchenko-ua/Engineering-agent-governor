import pexpect

child = pexpect.spawn(
    "chatbang",
    encoding="utf-8",
    timeout=120,
)

# Чекаємо перший prompt
child.expect("> ")

messages = [
    "hi",
    "Are you not tired?",
]

for msg in messages:
    print(f"\nUSER: {msg}")
    child.sendline(msg)

    # Чекаємо наступний prompt після відповіді
    child.expect("> ")

    response = child.before.strip()

    # child.before часто містить echo введеного повідомлення,
    # тому можна прибрати перший рядок, якщо потрібно
    lines = response.splitlines()
    if lines and lines[0].strip() == msg:
        response = "\n".join(lines[1:]).strip()

    print(f"BOT:\n{response}")

# Аналог Ctrl+C
child.sendcontrol("c")
child.close()