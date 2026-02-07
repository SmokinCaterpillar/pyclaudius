# Windows Setup

Windows has several options for running pyclaudius as an always-on service.

## Option 1: Task Scheduler (Built-in)

The simplest approach using Windows' built-in scheduler.

### Steps:

1. **Open Task Scheduler**
   - Press `Win + R`, type `taskschd.msc`, press Enter

2. **Create New Task**
   - Click "Create Task" (not "Create Basic Task" for more options)

3. **General Tab**
   - Name: `pyclaudius`
   - Check "Run whether user is logged on or not"
   - Check "Run with highest privileges"

4. **Triggers Tab**
   - New > At startup
   - Or: New > At log on (if you prefer)

5. **Actions Tab**
   - New > Start a program
   - Program: `C:\Users\YOUR_USERNAME\.local\bin\uv.exe`
   - Arguments: `run pyclaudius`
   - Start in: `C:\path\to\pyclaudius`

6. **Settings Tab**
   - Check "If the task fails, restart every: 1 minute"
   - Check "Attempt to restart up to: 999 times"
   - Uncheck "Stop the task if it runs longer than"

7. **Click OK** and enter your password when prompted

### Commands:

```powershell
# Check if running
schtasks /query /tn "pyclaudius"

# Start manually
schtasks /run /tn "pyclaudius"

# Stop
schtasks /end /tn "pyclaudius"
```

---

## Option 2: NSSM (Windows Service)

NSSM (Non-Sucking Service Manager) turns any program into a proper Windows service.

### Install:

1. Download from https://nssm.cc/download
2. Extract to `C:\nssm`
3. Add to PATH or use full path

### Setup:

```powershell
# Install as service (opens GUI)
nssm install pyclaudius

# Or via command line:
nssm install pyclaudius "C:\Users\YOUR_USERNAME\.local\bin\uv.exe" "run pyclaudius"
nssm set pyclaudius AppDirectory "C:\path\to\pyclaudius"
nssm set pyclaudius DisplayName "pyclaudius Telegram Bot"
nssm set pyclaudius Description "Telegram bot relay for Claude Code"
nssm set pyclaudius Start SERVICE_AUTO_START

# Set environment variables
nssm set pyclaudius AppEnvironmentExtra HOME=C:\Users\YOUR_USERNAME

# Start the service
nssm start pyclaudius
```

### Commands:

```powershell
nssm status pyclaudius   # Check status
nssm stop pyclaudius     # Stop
nssm start pyclaudius    # Start
nssm restart pyclaudius  # Restart
nssm remove pyclaudius   # Uninstall (confirm prompt)
```

---

## Troubleshooting

### Common Issues:

1. **"uv not found"**
   - Use full path: `C:\Users\YOUR_USERNAME\.local\bin\uv.exe`
   - Or add uv to system PATH

2. **"claude not found"**
   - Ensure Claude Code is installed: `npm install -g @anthropic-ai/claude-code`
   - Use full path in CLAUDE_PATH env variable

3. **Environment variables not loading**
   - For Task Scheduler: Set them in the task's "Actions" settings
   - For NSSM: Use `nssm set pyclaudius AppEnvironmentExtra VAR=value`

4. **Service won't start**
   - Check logs in Event Viewer > Windows Logs > Application
   - Run manually first to check for errors: `uv run pyclaudius`

### Logs Location:

- Task Scheduler: Configure in task settings
- NSSM: Configure with `nssm set pyclaudius AppStdout C:\path\to\log.txt`
