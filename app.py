from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

KANNOZAKI_LAT = 35.255
KANNOZAKI_LON = 139.742
TIMEZONE = 'Asia/Tokyo'

BOAT_SOURCES = [
    {
        'name': '教至丸',
        'url': 'https://www.noriyukimaru.net/',
        'type': 'generic',
    },
    {
        'name': '海福丸',
        'url': 'https://www.kaifukumaru.net/',
        'type': 'generic',
    },
    {
        'name': '関義丸',
        'url': 'https://sekiyoshimaru.com/catch.html',
        'type': 'generic',
    },
    {
        'name': 'おかだ丸',
        'url': 'https://www.marines-net.co.jp/fishing_archive/okadamaru',
        'type': 'generic',
    },
    {
        'name': '五郎丸',
        'url': 'https://www.gorou.co.jp/turika.htm',
        'type': 'generic',
    },
    {
        'name': 'かもい丸',
        'url': 'https://www.kamoimaru.com/category/Realtime/1/',
        'type': 'generic',
    },
    {
        'name': '巳之助丸',
        'url': 'https://www.minosukemaru.com/category/Choka/',
        'type': 'generic',
    },
]

USER_AGENT = (
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
    'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
)


@dataclass
class BoatResult:
    boat_name: str
    found: bool
    title: str = ''
    fish: str = ''
    size: str = ''
    catch_range: str = ''
    area_depth: str = ''
    comment: str = ''
    source_url: str = ''
    source_name: str = ''


def fetch_text(url: str) -> str:
    r = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=20)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    return r.text


def clean_text(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()


def date_candidates(target: date) -> list[str]:
    cands = [
        target.strftime('%Y/%m/%d'),
        f'{target.year}/{target.month}/{target.day}',
        target.strftime('%Y-%m-%d'),
        f'{target.year}-{target.month}-{target.day}',
        target.strftime('%Y.%m.%d'),
        f'{target.year}.{target.month}.{target.day}',
        target.strftime('%Y年%m月%d日'),
        f'{target.year}年{target.month}月{target.day}日',
        f'{target.month}月{target.day}日',
        f'{target.month}/{target.day}',
        f'{target.month}.{target.day}',
        f'{target.day}日の',
        f'{target.day}日 ',
    ]
    # preserve order, remove duplicates/empties
    out: list[str] = []
    for c in cands:
        c = c.strip()
        if c and c not in out:
            out.append(c)
    return out


def parse_generic_boat_site(html: str, target: date, boat_name: str, source_url: str) -> BoatResult:
    text = BeautifulSoup(html, 'html.parser').get_text('\n')

    idx = -1
    matched = ''
    for d in date_candidates(target):
        idx = text.find(d)
        if idx >= 0:
            matched = d
            break

    if idx < 0:
        # some sites only show recent rows; for same month pages a bare day can still be useful
        day_match = re.search(rf'(^|\D){target.day}日', text)
        if day_match:
            idx = max(0, day_match.start() - 10)
            matched = f'{target.day}日'

    if idx < 0:
        return BoatResult(boat_name=boat_name, found=False, source_url=source_url, source_name=boat_name)

    snippet = text[max(0, idx - 120): idx + 3500]
    snippet = clean_text(snippet)

    fish = 'アジ' if 'アジ' in snippet else ''
    title = ''
    size = ''
    catch_range = ''
    area_depth = ''
    comment = ''

    m_title = re.search(r'(ショートアジ船|午前アジ船|午後アジ船|アジ船|ビシアジ|ショート アジ)', snippet)
    if m_title:
        title = clean_text(m_title.group(1)).replace('ショート アジ', 'ショートアジ船')

    m_size = re.search(r'([0-9]{1,2}\s*[-〜~]\s*[0-9]{1,2}\s*cm)', snippet)
    if m_size:
        size = clean_text(m_size.group(1))

    m_catch = re.search(r'([0-9]{1,3}\s*[〜~〜-]\s*[0-9]{1,3}\s*(?:匹|尾))', snippet)
    if m_catch:
        catch_range = clean_text(m_catch.group(1)).replace('尾', '匹')
    else:
        # sometimes written as 4〜15尾 4〜51尾 in two-boat style pages
        all_counts = re.findall(r'([0-9]{1,3}\s*[〜~〜-]\s*[0-9]{1,3}\s*(?:匹|尾))', snippet)
        if all_counts:
            catch_range = ' / '.join(clean_text(x).replace('尾', '匹') for x in all_counts[:2])

    m_area = re.search(r'(?:釣り場と水深[:：]?\s*)?((?:走水沖|久里浜沖|観音崎沖|鴨居沖)[^。]{0,40}?\d+\s*M(?:\s*[〜~－-]\s*\d+\s*M)?)', snippet)
    if m_area:
        area_depth = clean_text(m_area.group(1))
    else:
        m_depth_only = re.search(r'((?:\d+\s*M前後)|(?:\d+\s*M(?:\s*[〜~－-]\s*\d+\s*M)?))', snippet)
        if m_depth_only:
            area_depth = clean_text(m_depth_only.group(1))

    comment_patterns = [
        r'船長コメント[:：]?\s*(.*?)(?:posted by|\d{1,2}:\d{2}\s*\||Image:|$)',
        r'(?:コメント[:：]?\s*)(.*?)(?:posted by|\d{1,2}:\d{2}\s*\||Image:|$)',
        r'(?:アジ[^。]{0,50}(?:匹|尾)[。\s]+)(.*?)(?:posted by|\d{1,2}:\d{2}\s*\||Image:|$)',
    ]
    for pat in comment_patterns:
        m = re.search(pat, snippet, re.S)
        if m:
            comment = clean_text(m.group(1))[:320]
            if comment:
                break

    if not comment:
        lines = [clean_text(x) for x in snippet.split('。') if clean_text(x)]
        keep = [ln for ln in lines if any(k in ln for k in ['ポツポツ', '好調', '苦戦', '大型', '良型', '皆様', 'お土産', '反応'])]
        comment = '。'.join(keep[:3])[:320]

    found = bool(fish or size or catch_range or area_depth or comment)
    return BoatResult(
        boat_name=boat_name,
        found=found,
        title=title or 'アジ船',
        fish=fish or 'アジ',
        size=size,
        catch_range=catch_range,
        area_depth=area_depth,
        comment=comment,
        source_url=source_url,
        source_name=boat_name,
    )


def get_boat_results(target: date) -> list[BoatResult]:
    out: list[BoatResult] = []
    for src in BOAT_SOURCES:
        try:
            html = fetch_text(src['url'])
            result = parse_generic_boat_site(html, target, src['name'], src['url'])
            out.append(result)
        except Exception as e:
            out.append(BoatResult(
                boat_name=src['name'],
                found=False,
                comment=f'取得エラー: {e}',
                source_url=src['url'],
                source_name=src['name'],
            ))
    return out


def extract_tide_day_block(text: str, target: date) -> str:
    candidates = [
        f'{target.month}月{target.day}日',
        target.strftime('%Y/%m/%d'),
        target.strftime('%Y-%m-%d'),
        target.strftime('%Y.%m.%d'),
    ]
    idx = -1
    used = ''
    for c in candidates:
        idx = text.find(c)
        if idx >= 0:
            used = c
            break
    if idx < 0:
        return ''
    tail = text[idx: idx + 1500]
    next_marker = f'{(target + timedelta(days=1)).month}月{(target + timedelta(days=1)).day}日'
    next_idx = tail.find(next_marker, len(used))
    if next_idx > 0:
        tail = tail[:next_idx]
    return tail


def parse_tide_events(block: str) -> list[dict[str, Any]]:
    events = []
    pattern = re.compile(r'(\d{1,2}:\d{2})\s*(満潮|干潮)\s*(\d+)cm')
    for tm, kind, cm in pattern.findall(block):
        h, m = map(int, tm.split(':'))
        minutes = h * 60 + m
        events.append({'time': tm, 'kind': kind, 'height_cm': int(cm), 'minutes': minutes})
    return events


def build_tide_series(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not events:
        return []
    pts = sorted(events, key=lambda x: x['minutes'])
    if pts[0]['minutes'] > 0:
        pts = [{'minutes': 0, 'height_cm': pts[0]['height_cm'], 'time': '00:00', 'kind': '補間'}] + pts
    if pts[-1]['minutes'] < 24 * 60 - 1:
        pts = pts + [{'minutes': 24 * 60 - 1, 'height_cm': pts[-1]['height_cm'], 'time': '23:59', 'kind': '補間'}]

    series = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        span = max(1, b['minutes'] - a['minutes'])
        step = 30
        t = a['minutes']
        while t < b['minutes']:
            ratio = (t - a['minutes']) / span
            h = round(a['height_cm'] + (b['height_cm'] - a['height_cm']) * ratio, 1)
            series.append({'time': f'{t//60:02d}:{t%60:02d}', 'height_cm': h})
            t += step
    series.append({'time': f"{pts[-1]['minutes']//60:02d}:{pts[-1]['minutes']%60:02d}", 'height_cm': pts[-1]['height_cm']})
    return series


def get_tide_info(target: date) -> dict[str, Any]:
    urls = [
        'https://fishingjapan.jp/shiomihyou/44/444626/21000/',
        'https://tide.chowari.jp/44/444626/21000/',
        'https://tide.chowari.jp/14/142018/21420/',
    ]
    for url in urls:
        try:
            html = fetch_text(url)
            text = BeautifulSoup(html, 'html.parser').get_text('\n')
            block = extract_tide_day_block(text, target)
            events = parse_tide_events(block)
            if events:
                tide_name = ''
                m_name = re.search(r'(大潮|中潮|小潮|長潮|若潮)', block)
                if m_name:
                    tide_name = m_name.group(1)
                return {
                    'events': events,
                    'series': build_tide_series(events),
                    'tide_name': tide_name,
                    'source_url': url,
                }
        except Exception:
            continue
    return {'events': [], 'series': [], 'tide_name': '', 'source_url': ''}


def weather_code_to_jp(code: int | None) -> str:
    mapping = {
        0: '快晴', 1: '晴れ', 2: '晴れ時々くもり', 3: 'くもり',
        45: '霧', 48: '着氷性の霧',
        51: '弱い霧雨', 53: '霧雨', 55: '強い霧雨',
        61: '弱い雨', 63: '雨', 65: '強い雨',
        71: '弱い雪', 73: '雪', 75: '大雪',
        80: 'にわか雨', 81: '強いにわか雨', 82: '激しいにわか雨',
        95: '雷雨', 96: '雷雨・ひょう', 99: '激しい雷雨・ひょう',
    }
    return mapping.get(code, f'天気コード {code}')


def get_weather_info(target: date) -> dict[str, Any]:
    today = datetime.now().date()
    if target < today:
        endpoint = 'https://archive-api.open-meteo.com/v1/archive'
    else:
        endpoint = 'https://api.open-meteo.com/v1/forecast'

    params = {
        'latitude': KANNOZAKI_LAT,
        'longitude': KANNOZAKI_LON,
        'timezone': TIMEZONE,
        'start_date': target.isoformat(),
        'end_date': target.isoformat(),
        'daily': 'temperature_2m_max,temperature_2m_min,weather_code',
        'hourly': 'temperature_2m,weather_code',
    }
    r = requests.get(endpoint, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    daily = data.get('daily', {})
    hourly = data.get('hourly', {})
    summary_code = None
    noon_temp = None

    hourly_times = hourly.get('time', [])
    hourly_codes = hourly.get('weather_code', [])
    hourly_temps = hourly.get('temperature_2m', [])
    target_noon = f'{target.isoformat()}T12:00'
    if target_noon in hourly_times:
        i = hourly_times.index(target_noon)
        summary_code = hourly_codes[i] if i < len(hourly_codes) else None
        noon_temp = hourly_temps[i] if i < len(hourly_temps) else None
    elif daily.get('weather_code'):
        summary_code = daily['weather_code'][0]

    return {
        'date': target.isoformat(),
        'weather': weather_code_to_jp(summary_code),
        'weather_code': summary_code,
        'temp_max': daily.get('temperature_2m_max', [None])[0],
        'temp_min': daily.get('temperature_2m_min', [None])[0],
        'noon_temp': noon_temp,
        'source_endpoint': endpoint,
    }


@app.route('/', methods=['GET'])
def index():
    q = request.args.get('date')
    target = datetime.now().date()
    if q:
        try:
            target = datetime.strptime(q, '%Y-%m-%d').date()
        except ValueError:
            pass

    boat_results = get_boat_results(target)
    tide = get_tide_info(target)
    weather = None
    weather_error = None
    try:
        weather = get_weather_info(target)
    except Exception as e:
        weather_error = str(e)

    available_boats = [src['name'] for src in BOAT_SOURCES]

    return render_template(
        'index.html',
        selected_date=target.isoformat(),
        boat_results=boat_results,
        tide=tide,
        weather=weather,
        weather_error=weather_error,
        generated_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
        boat_source_names='、'.join(available_boats),
        boat_count=len(available_boats),
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
