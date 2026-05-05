# [0.11.0]

* Email integration: fetch unseen emails from an IMAP account and save them as markdown
  - Telegram commands `/downloadnewmail` and `/deleteallreadmail`
  - MCP tools `download_new_mail` and `delete_read_mail`
  - For forwarded emails, the original sender is extracted from headers
    (X-Original-From, Resent-From, X-Original-Sender) or from the body's
    forward boilerplate (Gmail / Apple Mail / Outlook) and surfaced in the markdown


# [0.10.3]

* Refactor and simplify
* typing of BotData

# [0.10.2]

* BUG-FIX: use tmux if stale
* mcp taks callback

# [0.10.1]

* BUG-FIX: restart session if it is stale

# [0.10.0] - 2026-04-10

* Image reading fix
* System prompt fix

# [0.9.1] - 2026-04-03

* /context supported

# [0.9.0] - 2026-03-14

* using tmux session to keep claude alive
* allow for /clear and /compact

# [0.8.1] - 2026-03-13

* timeout on subprocess call
* New error handling

# [0.8.0] - 2026-02-11

* todo pile

# [0.7.0] -2026-02-08

* new mcp tooling setup

# [0.6.0] - 2026-02-09

* New cron functionality

# 0.5.1 -2026-02-08

* /forget <int> works to forget the ith fact, memory will issue a warning on overflow

# 0.5.0 -2026-02-08

* New /listmemory and /help functionality

# 0.4.1 - 2026-02-08

* Even less privileges for the systemd

# 0.4.0 - 2026-02-08

* Better security make claude no longer have access to .env and the code directory

# 0.3.2 -2026-02-08

* Bug fixing around tool use

# 0.3.1 - 2026-02-08

* New config of tools

# 0.3.0 - 2026-02-08

* New forgetting mechanism

# 0.2.1 - 2026-02-08

* Bug fixes for missing permissions for files
* Bug fixes for continuity with resume

# 0.2.0 - 2026-02-07

* New filebased memory

# 0.1.0 - 2026-02-07

* First one shot by Claude and me