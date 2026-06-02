import os
import io
import requests
from bs4 import BeautifulSoup
import yaml
import datetime
import re
import base64
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import resend
from supabase import create_client
from dotenv import load_dotenv
load_dotenv()

def load_db_config(path='database_config.yaml'):
    """Load schema/table values using PyYAML if available, otherwise fallback.
    Returns dict {'schema':..., 'table':...} with sensible defaults.
    """
    defaults = {'schema': 'fuel_data', 'table': 'data'}
    
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            parsed = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return defaults
    except Exception:
        return defaults

    if isinstance(parsed, dict):
        if 'supabase_fuel_data_table' in parsed and isinstance(parsed['supabase_fuel_data_table'], dict):
            node = parsed['supabase_fuel_data_table']
            return {'schema': node.get('schema', defaults['schema']), 'table': node.get('table', defaults['table'])}
        if 'supabase' in parsed and isinstance(parsed['supabase'], dict):
            node = parsed['supabase']
            return {'schema': node.get('schema', defaults['schema']), 'table': node.get('table', defaults['table'])}
        if 'schema' in parsed and 'table' in parsed:
            return {'schema': parsed.get('schema', defaults['schema']), 'table': parsed.get('table', defaults['table'])}

    return defaults

# Load DB schema/table config once
DB_CONFIG = load_db_config()

MONTHS_PL = {
    'stycznia': 1, 'lutego': 2, 'marca': 3, 'kwietnia': 4,
    'maja': 5, 'czerwca': 6, 'lipca': 7, 'sierpnia': 8,
    'wrzesnia': 9, 'pazdziernika': 10, 'listopada': 11, 'grudnia': 12,
}

MONTHS_DISPLAY = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia",
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}


def get_supabase_client():
    url = os.environ['SUPABASE_URL']
    key = os.environ['SUPABASE_KEY']
    return create_client(url, key)


def get_existing_dates(supabase):
    response = (
        supabase.schema(DB_CONFIG['schema'])
        .table(DB_CONFIG['table'])
        .select('price_date')
        .execute()
    )
    return {row['price_date'] for row in response.data}


def save_to_supabase(supabase, records):
    rows = [
        {
            'price_date': r['date'],
            'price_pb95': r['pb95'],
            'price_pb98': r['pb98'],
            'price_on': r['on'],
        }
        for r in records
    ]
    if rows:
        response = (
            supabase.schema(DB_CONFIG['schema'])
            .table(DB_CONFIG['table'])
            .insert(rows)
            .execute()
        )
        print(f"Inserted {len(response.data)} records into Supabase.")
    else:
        print("No new records to insert.")


def get_urls_from_gov():
    print("Fetching data from gov.pl...")
    url = "https://www.gov.pl/web/energia/wiadomosci"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')

        urls = []
        for title_div in soup.find_all('div', class_='title'):
            link = title_div.find('a')
            if link and 'Maksymalna cena detaliczna paliw' in link.get_text():
                full_url = "https://www.gov.pl" + link['href']
                urls.append(full_url)

        print(f"Found {len(urls)} URLs with fuel price information on the first page.")
        if urls:
            for u in urls:
                print(f"  - {u}")
        return urls
    except Exception as e:
        print(f"Error: {e}")
        return []


def parse_dates_from_url(url):
    slug = url.split('/')[-1]
    # Handle ranges in the slug. There are a few formats observed on gov.pl:
    # - same-month range: '23-25-maja-2026'
    # - multi-month range: '30-maja--1-czerwca-2026' (note the double hyphen)
    # Try same-month first, then a multi-month range fallback.
    if 'okres' in slug:
        # same-month range: start-end-month-year
        match = re.search(r"(\d{1,2})-(\d{1,2})-([a-ząćęłńóśżź]+)-(\d{4})", slug, re.IGNORECASE)
        if match:
            day_start = int(match.group(1))
            day_end = int(match.group(2))
            month = MONTHS_PL.get(match.group(3).lower())
            year = int(match.group(4))
            if month:
                return [datetime.date(year, month, day) for day in range(day_start, day_end + 1)]

        # multi-month range: day1-month1--day2-month2-year (allow one or more hyphens)
        match2 = re.search(r"(\d{1,2})-([a-ząćęłńóśżź]+)-+(\d{1,2})-([a-ząćęłńóśżź]+)-(\d{4})", slug, re.IGNORECASE)
        if match2:
            day1 = int(match2.group(1))
            month1 = MONTHS_PL.get(match2.group(2).lower())
            day2 = int(match2.group(3))
            month2 = MONTHS_PL.get(match2.group(4).lower())
            year = int(match2.group(5))
            if month1 and month2:
                start = datetime.date(year, month1, day1)
                end = datetime.date(year, month2, day2)
                # build inclusive list of dates between start and end
                dates = []
                cur = start
                while cur <= end:
                    dates.append(cur)
                    cur = cur + datetime.timedelta(days=1)
                return dates
    else:
        match = re.search(r"(\d{1,2})-([a-ząćęłńóśżź]+)-(\d{4})", slug, re.IGNORECASE)
        if match:
            day = int(match.group(1))
            month = MONTHS_PL.get(match.group(2).lower())
            year = int(match.group(3))
            if month:
                return [datetime.date(year, month, day)]

    return []


def scrape_prices_from_url(url):
    regex_b95 = r"(?i)benzyna\s*95.{0,40}?(\d+[.,]\d{2})"
    regex_b98 = r"(?i)benzyna\s*98.{0,40}?(\d+[.,]\d{2})"
    regex_on = r"(?i)olej[u]?\s+nap[ęe]dow.{0,40}?(\d+[.,]\d{2})"

    pb95_price = None
    pb98_price = None
    on_price = None

    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        text = soup.get_text()

        pb95 = re.search(regex_b95, text)
        pb98 = re.search(regex_b98, text)
        on = re.search(regex_on, text)

        pb95_price = float(pb95.group(1).replace(',', '.')) if pb95 else None
        pb98_price = float(pb98.group(1).replace(',', '.')) if pb98 else None
        on_price = float(on.group(1).replace(',', '.')) if on else None
    except Exception as e:
        print(f"  Error scraping {url}: {e}")

    dates = parse_dates_from_url(url)
    return [{'date': d.isoformat(), 'pb95': pb95_price, 'pb98': pb98_price, 'on': on_price} for d in dates]


def scrape_and_store(supabase):
    """Scrape new fuel prices and store in Supabase. Returns True if new data was added."""
    existing_dates = get_existing_dates(supabase)
    print(f"Already have {len(existing_dates)} dates in database.")

    urls = get_urls_from_gov()

    urls_to_scrape = []
    for url in urls:
        dates = parse_dates_from_url(url)
        if any(d.isoformat() not in existing_dates for d in dates):
            urls_to_scrape.append(url)

    if not urls_to_scrape:
        print("All dates already in database. Nothing to scrape.")
        return False

    print(f"{len(urls_to_scrape)} URLs have new dates to scrape.")
    

    all_data = []
    for url in urls_to_scrape:
        rows = scrape_prices_from_url(url)
        # Print whatever the scraper returned for this URL
        print(f"Results from URL {url} was found:")
        if rows:
            for r in rows:
                print(f"  {r['date']}  PB95={r['pb95']}  PB98={r['pb98']}  ON={r['on']}")
        else:
            print("  No results from this URL.")
        new_rows = [r for r in rows if r['date'] not in existing_dates]
        all_data.extend(new_rows)

    if not all_data:
        print("No new records after filtering.")
        return False

    print(f"Collected {len(all_data)} new price records.")
    for row in all_data:
        print(f"  {row['date']}  PB95={row['pb95']}  PB98={row['pb98']}  ON={row['on']}")

    save_to_supabase(supabase, all_data)
    return True


def get_records_from_supabase(supabase, count=10):
    response = (
        supabase.schema(DB_CONFIG['schema'])
        .table(DB_CONFIG['table'])
        .select('created_at, price_date, price_pb95, price_pb98, price_on')
        .order('price_date', desc=True)
        .limit(count)
        .execute()
    )
    return response.data


def build_dataframe(records):
    df = pd.DataFrame(records)
    df['date'] = pd.to_datetime(df['price_date'])
    df = df.sort_values('date').set_index('date')
    df['created_at'] = pd.to_datetime(df['created_at'])
    df['Petrol 95'] = pd.to_numeric(df['price_pb95'])
    df['Petrol 98'] = pd.to_numeric(df['price_pb98'])
    df['Diesel'] = pd.to_numeric(df['price_on'])
    return df


def generate_chart_base64(df):
    plt.figure(figsize=(18, 10))
    colors = {'Petrol 95': '#2ca02c', 'Petrol 98': '#1f77b4', 'Diesel': '#333333'}

    for col in ['Petrol 95', 'Petrol 98', 'Diesel']:
        plt.plot(df.index, df[col], marker='o', label=col, color=colors[col], linewidth=3, markersize=8)

    for date, row in df.iterrows():
        bg_color = "#FFFFFF"
        p95, p98, diesel = row['Petrol 95'], row['Petrol 98'], row['Diesel']

        plt.annotate(f"{p98:.2f}", xy=(date, p98), xytext=(0, 10), textcoords="offset points",
                    ha='center', fontsize=22, weight='bold',
                    bbox=dict(boxstyle="round,pad=0.3", fc=bg_color, ec="gray", lw=0.5, alpha=0.9))

        plt.annotate(f"{p95:.2f}", xy=(date, p95), xytext=(0, -18), textcoords="offset points",
                    ha='center', fontsize=22, weight='bold',
                    bbox=dict(boxstyle="round,pad=0.3", fc=bg_color, ec="gray", lw=0.5, alpha=0.9))

        plt.annotate(f"{diesel:.2f}", xy=(date, diesel), xytext=(0, 10), textcoords="offset points",
                    ha='center', fontsize=22, weight='bold',
                    bbox=dict(boxstyle="round,pad=0.4", fc=bg_color, ec="gray", lw=0.5, alpha=0.9))

    plt.title('Daily maximum retail fuel prices (PLN/liter)', fontsize=20, pad=20)
    plt.xlabel('Date', fontsize=14)
    plt.ylabel('Price (PLN)', fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.5)

    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%d-%m'))
    plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.gcf().autofmt_xdate()

    plt.ylim(df[['Petrol 95', 'Petrol 98', 'Diesel']].min().min() - 0.15,
            df[['Petrol 95', 'Petrol 98', 'Diesel']].max().max() + 0.15)

    plt.legend(loc='upper left', fontsize=14)
    plt.tick_params(axis='both', labelsize=12)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=300)
    plt.close()
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    print("Chart generated in memory.")
    return img_base64


def build_email_subject(df):
    # Match SQL logic: among the recent rows, use only those with the latest created_at
    if df.empty:
        return "Brak ostatnich cen paliw w bazie danych"

    if 'created_at' in df.columns and not df['created_at'].isna().all():
        max_created = df['created_at'].max()
        subset = df[df['created_at'] == max_created]
        if not subset.empty:
            start = subset.index.min()
            end = subset.index.max()
        else:
            start = df.index.min()
            end = df.index.max()
    else:
        start = df.index.min()
        end = df.index.max()

    start_txt = f"{start.day} {MONTHS_DISPLAY[start.month]} {start.year}"
    end_txt = f"{end.day} {MONTHS_DISPLAY[end.month]} {end.year}"
    return f"Najnowszy raport cen paliw, uwzględniający dane od {start_txt} do {end_txt}"


def build_html_email(df, chart_base64):
    title = build_email_subject(df)
    today = datetime.date.today().strftime('%d.%m.%Y')

    rows_html = ""
    for date, row in df.iloc[::-1].iterrows():
        rows_html += f"""<tr>
            <td style="padding:6px 12px;border:1px solid #ddd;">{date.strftime('%d.%m.%Y')}</td>
            <td style="padding:6px 12px;border:1px solid #ddd;text-align:right;">{row['Petrol 95']:.2f}</td>
            <td style="padding:6px 12px;border:1px solid #ddd;text-align:right;">{row['Petrol 98']:.2f}</td>
            <td style="padding:6px 12px;border:1px solid #ddd;text-align:right;">{row['Diesel']:.2f}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;margin:0;padding:20px;background:#f9f9f9;">
    <div style="max-width:800px;margin:0 auto;background:#fff;border-radius:8px;padding:30px;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
        <h1 style="color:#333;font-size:22px;margin-bottom:5px;">⛽ Raport cen paliw</h1>
        <p style="color:#666;font-size:14px;margin-top:0;">{today}</p>

        <div style="background:#f0f7ff;border-left:4px solid #1f77b4;padding:12px 16px;margin:20px 0;border-radius:4px;">
            <strong style="font-size:16px;">{title}</strong>
        </div>

        <h2 style="color:#555;font-size:16px;margin-top:30px;">Wykres cen za ostatnie dni</h2>
        <img src="cid:chart" alt="Fuel price chart" style="width:100%;max-width:750px;border-radius:4px;margin:10px 0;" />

        <h2 style="color:#555;font-size:16px;margin-top:30px;">Tabela cen (PLN/l)</h2>
        <table style="border-collapse:collapse;width:100%;font-size:14px;">
            <thead>
                <tr style="background:#f5f5f5;">
                    <th style="padding:8px 12px;border:1px solid #ddd;text-align:left;">Data</th>
                    <th style="padding:8px 12px;border:1px solid #ddd;text-align:right;">PB95</th>
                    <th style="padding:8px 12px;border:1px solid #ddd;text-align:right;">PB98</th>
                    <th style="padding:8px 12px;border:1px solid #ddd;text-align:right;">ON</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <p style="color:#999;font-size:11px;margin-top:30px;border-top:1px solid #eee;padding-top:10px;">
            Dane pochodzą z: gov.pl/web/energia | Wiersze zaznaczone na różowo to dni bez publikacji (skopiowane z poprzedniego dnia).
        </p>
    </div>
</body>
</html>"""
    return html


def send_email(html_content, chart_base64, subject):
    resend.api_key = os.environ['RESEND_KEY']
    for recipient in os.environ['EMAIL_TO'].split(','):

        r = resend.Emails.send({
            "from": os.environ.get('EMAIL_FROM'),
            "to": recipient.strip(),
            "subject": subject,
            "html": html_content,
            "attachments": [
                {
                    "filename": "fuel_report.png",
                    "content": chart_base64,
                    "content_id": "chart",
                }
            ],
        })
        print(f"Email sent to {recipient.strip()} via Resend. ID: {r.get('id', r)}")


def generate_report_and_send(supabase):
    records = get_records_from_supabase(supabase, count=10)
    if not records:
        print("No records found in database.")
        return

    df = build_dataframe(records)
    chart_base64 = generate_chart_base64(df)
    html_content = build_html_email(df, chart_base64)
    subject = build_email_subject(df)

    print(f"Subject: {subject}")
    send_email(html_content, chart_base64, subject)


def main():
    print("Starting fuel price scraper and reporter...")
    supabase = get_supabase_client()
    
    new_data_added = scrape_and_store(supabase)
    force_email = os.environ.get('FORCE_SEND_EMAIL', 'false').lower() == 'true'

    if new_data_added or force_email:
        generate_report_and_send(supabase)
    else:
        print("No new data added. Skipping email.")

    # Show last 5 entries from the database in the terminal
    try:
        last_records = get_records_from_supabase(supabase, count=5)
        if last_records:
            print("\nLast 5 records from database:")
            for r in last_records:
                print(f"  {r.get('price_date')}  PB95={r.get('price_pb95')}  PB98={r.get('price_pb98')}  ON={r.get('price_on')}")
        else:
            print("No records found in database.")
    except Exception as e:
        print(f"Error fetching last records: {e}")


if __name__ == "__main__":
    main()
