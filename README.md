## fuel-prices

Small utility that scrapes the Polish government energy page for the daily maximum retail fuel prices, stores the data in Supabase, generates a chart and an HTML report, and sends the report by email via Resend.

**Key features**
- Scrapes `gov.pl/web/energia` for posts titled “Maksymalna cena detaliczna paliw” and parses price values for PB95, PB98 and ON.
- Stores new daily records in a Supabase table `fuel_data.data`.
- Generates a PNG chart and an HTML email report (with an embedded chart) and sends it using Resend.

## Requirements
- Python 3.13 or newer
- The dependencies listed in `pyproject.toml`: `beautifulsoup4`, `matplotlib`, `pandas`, `requests`, `resend`, `supabase`, `dotenv`.

## Install
This project can use the `uv` package manager (https://uv.run) to install dependencies from `pyproject.toml`.

Install `uv` (recommended via `pipx`) and then install project dependencies:

```bash
# install uv (pipx recommended)
pipx install uv

# in the project root, install deps from pyproject.toml
uv install
```

If you prefer not to use `uv`, you can still create a virtual environment and install the packages manually:

```bash
python -m venv .venv
source .venv/bin/activate
pip install beautifulsoup4 matplotlib pandas requests resend supabase
```

## Configuration
The script expects the following environment variables to be set:

- `SUPABASE_URL` — your Supabase project URL
- `SUPABASE_KEY` — your Supabase anon or service key with write access to the `fuel_data.data` table
- `RESEND_KEY` — API key for Resend (used to send the report email)
- `EMAIL_FROM` — your email resend domain email
- `EMAIL_TO` — email recipient
- (optional) `FORCE_SEND_EMAIL` — set to `true` to force sending the email even if no new data were scraped

Example (macOS / Linux):

```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_KEY="your-supabase-key"
export RESEND_KEY="your-resend-key"
export EMAIL_FROM="from@example.com"
export EMAIL_TO="to@example.com"
export FORCE_SEND_EMAIL=false
```

Windows (PowerShell) — temporary for current session:

```powershell
$env:SUPABASE_URL = "https://your-project.supabase.co"
$env:SUPABASE_KEY = "your-supabase-key"
$env:RESEND_KEY = "your-resend-key"
$env:EMAIL_FROM="from@example.com"
$env:EMAIL_TO="to@example.com"
$env:FORCE_SEND_EMAIL = "false"
```

Windows (PowerShell) — persistent (use `setx` to write to user environment):

```powershell
setx SUPABASE_URL "https://your-project.supabase.co"
setx SUPABASE_KEY "your-supabase-key"
setx RESEND_KEY "your-resend-key"
setx EMAIL_FROM="from@example.com"
setx EMAIL_TO="to@example.com"
setx FORCE_SEND_EMAIL "false"
```

Using a `.env` file

You can store environment variables in a `.env` file in the project root. Example `.env`:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-key
RESEND_KEY=your-resend-key
EMAIL_FROM="from@example.com"
EMAIL_TO="to@example.com"
FORCE_SEND_EMAIL=false
```

To load `.env` automatically when running `main.py`, install `python-dotenv` and add a call to `load_dotenv()` at the top of `main.py`:

```bash
pip install python-dotenv
```

Then in `main.py`, near the other imports add:

```python
from dotenv import load_dotenv
load_dotenv()
```
This makes `os.environ` pick up values from `.env` during runtime.

## Usage
After configuration and activating the venv, run:

```bash
python main.py
```

What `main.py` does:
- Connects to Supabase using `SUPABASE_URL` and `SUPABASE_KEY`.
- Fetches the government energy news page and finds links containing price announcements.
- Parses dates and prices (PB95, PB98, ON) from each announcement and inserts new records into Supabase.
- If new records were inserted (or `FORCE_SEND_EMAIL=true`), generates a chart, builds an HTML report and sends it via Resend to the configured address in the code.

## Supabase table expectations
The code writes into the `fuel_data.data` table with columns at least matching:
- `price_date` (ISO date string)
- `price_pb95` (numeric)
- `price_pb98` (numeric)
- `price_on` (numeric)
- `price_copied` (boolean, optional)

Adjust your Supabase schema/permissions as needed before running.

## Scheduling
This script is intended to be run periodically (daily). Due to gitgub limit and restrictions to trigger the job is using [cron-job.com](https://console.cron-job.org/jobs) service

## Development notes
- The parser includes heuristics for Polish month names and several slug formats used on `gov.pl` announcement URLs.
- Chart generation uses Matplotlib with `Agg` backend for headless environments.

## Troubleshooting
- If scraping returns no results, check whether the gov.pl page structure changed or the announcement titles differ.
- If emails are not sent, verify `RESEND_KEY` and the Resend account. The `send_email` function currently uses a hard-coded sender and recipient — update as needed in `main.py`.

## License
MIT
