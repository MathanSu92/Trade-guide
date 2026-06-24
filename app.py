
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date, time
import yfinance as yf
import feedparser
from urllib.parse import quote_plus
from pathlib import Path

st.set_page_config(page_title="Trading Guardrail Bot", layout="wide")

JOURNAL_PATH = Path("trading_journal.csv")

DEFAULT_WATCHLIST = {
    "DAX ETF (EXS1.DE)": "EXS1.DE",
    "iShares Core DAX ETF (EXS1.DE)": "EXS1.DE",
    "SAP": "SAP.DE",
    "Siemens": "SIE.DE",
    "Allianz": "ALV.DE",
    "Deutsche Telekom": "DTE.DE",
    "Mercedes-Benz": "MBG.DE",
    "Infineon": "IFX.DE",
    "Rheinmetall": "RHM.DE",
    "Airbus": "AIR.DE",
    "ASML": "ASML.AS",
    "LVMH": "MC.PA",
    "TotalEnergies": "TTE.PA",
    "NVIDIA": "NVDA",
    "Apple": "AAPL",
    "Microsoft": "MSFT",
    "Nasdaq 100 ETF": "QQQ",
    "S&P 500 ETF": "SPY",
}

HIGH_RISK_KEYWORDS = [
    "fed", "ecb", "ezb", "inflation", "cpi", "ppi", "jobs", "arbeitsmarkt",
    "payrolls", "rate decision", "zinsentscheidung", "war", "krieg",
    "tariff", "zoll", "sanction", "sanktion", "earnings", "quartalszahlen",
    "guidance", "profit warning", "gewinnwarnung", "election", "wahl"
]

def money(x):
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

@st.cache_data(ttl=300)
def load_prices(ticker: str, period: str = "6mo"):
    df = yf.download(ticker, period=period, interval="1d", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return df.dropna()

@st.cache_data(ttl=900)
def fetch_news(query: str, max_items: int = 8):
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=de&gl=DE&ceid=DE:de"
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries[:max_items]:
        title = entry.get("title", "")
        published = entry.get("published", "")
        link = entry.get("link", "")
        text = f"{title} {entry.get('summary', '')}".lower()
        risk_hits = sorted({kw for kw in HIGH_RISK_KEYWORDS if kw in text})
        items.append({
            "Titel": title,
            "Datum": published,
            "Risikowörter": ", ".join(risk_hits),
            "Link": link,
            "RisikoScore": min(100, len(risk_hits) * 20)
        })
    return pd.DataFrame(items)

def indicators(df: pd.DataFrame):
    out = df.copy()
    out["SMA20"] = out["Close"].rolling(20).mean()
    out["SMA50"] = out["Close"].rolling(50).mean()
    prev_close = out["Close"].shift(1)
    tr = pd.concat([
        out["High"] - out["Low"],
        (out["High"] - prev_close).abs(),
        (out["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    out["ATR14"] = tr.rolling(14).mean()
    out["Vol20"] = out["Volume"].rolling(20).mean()
    out["Return5"] = out["Close"].pct_change(5)
    return out

def make_signal(row):
    score = 0
    reasons = []
    block = []

    if pd.isna(row.get("SMA20")) or pd.isna(row.get("SMA50")) or pd.isna(row.get("ATR14")):
        return 0, ["Zu wenig Daten"], ["BLOCK: Indikatoren nicht verfügbar"]

    close = float(row["Close"])
    sma20 = float(row["SMA20"])
    sma50 = float(row["SMA50"])
    atr = float(row["ATR14"])
    vol = float(row.get("Volume", 0))
    vol20 = float(row.get("Vol20", 0))

    if close > sma20 > sma50:
        score += 35
        reasons.append("Trend positiv: Kurs > SMA20 > SMA50")
    elif close < sma20 < sma50:
        score -= 35
        block.append("Abwärtstrend: Kurs < SMA20 < SMA50")
    else:
        reasons.append("Trend uneindeutig")

    atr_pct = atr / close
    if 0.008 <= atr_pct <= 0.04:
        score += 25
        reasons.append(f"ATR im handelbaren Bereich: {atr_pct:.2%}")
    elif atr_pct > 0.06:
        score -= 40
        block.append(f"Volatilität sehr hoch: ATR {atr_pct:.2%}")
    else:
        score += 5
        reasons.append(f"Volatilität niedrig/moderat: ATR {atr_pct:.2%}")

    if vol20 and vol >= 0.8 * vol20:
        score += 20
        reasons.append("Volumen ausreichend")
    else:
        score -= 15
        block.append("Volumen unter Durchschnitt")

    ret5 = row.get("Return5", np.nan)
    if pd.notna(ret5):
        if ret5 > 0.08:
            score -= 15
            block.append(f"5-Tage-Bewegung schon stark: {ret5:.2%}")
        elif ret5 > 0:
            score += 10
            reasons.append(f"5-Tage-Momentum positiv: {ret5:.2%}")

    return max(0, min(100, score)), reasons, block

def calc_position(capital, max_position_pct, risk_per_trade, entry, stop, target):
    if entry <= 0 or stop <= 0 or target <= 0:
        return None
    risk_per_share = abs(entry - stop)
    if risk_per_share == 0:
        return None
    shares_by_risk = risk_per_trade / risk_per_share
    max_position_value = capital * max_position_pct
    shares_by_capital = max_position_value / entry
    shares = np.floor(min(shares_by_risk, shares_by_capital))
    if shares < 1:
        shares = 0
    position_value = shares * entry
    loss_at_stop = shares * risk_per_share
    gain_at_target = shares * abs(target - entry)
    rr = gain_at_target / loss_at_stop if loss_at_stop else 0
    return shares, position_value, loss_at_stop, gain_at_target, rr

def load_journal():
    if JOURNAL_PATH.exists():
        return pd.read_csv(JOURNAL_PATH)
    return pd.DataFrame(columns=[
        "Datum", "Ticker", "Richtung", "Einstieg", "Stop", "Ziel", "Stückzahl",
        "Risiko", "Chance", "Setup", "Status", "Notiz"
    ])

def save_journal(row):
    df = load_journal()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(JOURNAL_PATH, index=False)

st.title("Trading Guardrail Bot")
st.caption("Manueller Daytrading-Planer. Keine Anlageberatung, keine Garantie, keine automatische Orderausführung.")

with st.sidebar:
    st.header("Risikoregeln")
    capital = st.number_input("Kontokapital (€)", min_value=100.0, value=1000.0, step=50.0)
    daily_stop = st.number_input("Max. Tagesverlust (€)", min_value=10.0, value=150.0, step=10.0)
    daily_target = st.number_input("Tagesgewinn-Ziel (€)", min_value=10.0, value=150.0, step=10.0)
    max_trades = st.number_input("Max. Trades pro Tag", min_value=1, max_value=10, value=2, step=1)
    risk_per_trade = st.number_input("Max. Risiko pro Trade (€)", min_value=5.0, value=75.0, step=5.0)
    max_position_pct = st.slider("Max. Kapitalbindung pro Position", min_value=0.05, max_value=1.0, value=0.5, step=0.05)
    block_high_news = st.checkbox("Bei Risikonews blockieren", value=True)
    st.divider()
    custom = st.text_area("Eigene Watchlist, ein Yahoo-Ticker pro Zeile", value="")
    run = st.button("Tagescheck starten", type="primary")

st.warning(
    "Bei 1.000 € Kapital sind 100–200 € Tagesrisiko sehr aggressiv. "
    "Der Bot soll dich vor schlechten Setups schützen, nicht sichere Gewinne erzeugen."
)

watchlist = DEFAULT_WATCHLIST.copy()
if custom.strip():
    for line in custom.splitlines():
        t = line.strip()
        if t:
            watchlist[t] = t

tab1, tab2, tab3 = st.tabs(["Tagescheck", "Positionsrechner", "Journal"])

with tab1:
    st.subheader("Markt- und News-Check")
    if run:
        rows = []
        news_blocks = {}

        for name, ticker in watchlist.items():
            try:
                df = load_prices(ticker)
                if df.empty or len(df) < 60:
                    continue
                ind = indicators(df)
                latest = ind.iloc[-1]
                score, reasons, blocks = make_signal(latest)

                news_df = fetch_news(f"{ticker} OR {name} Börse Aktie Wirtschaft Politik")
                news_risk = int(news_df["RisikoScore"].max()) if not news_df.empty else 0
                if block_high_news and news_risk >= 40:
                    blocks.append("Risikonews vorhanden")

                close = float(latest["Close"])
                atr = float(latest["ATR14"])
                # Long-only Vorschlag, konservativ: Stop 1 ATR, Target 2 ATR
                entry = close
                stop = close - atr
                target = close + 2 * atr
                pos = calc_position(capital, max_position_pct, risk_per_trade, entry, stop, target)

                status = "OK prüfen"
                if blocks or score < 60:
                    status = "BLOCK / kein Trade"

                if pos:
                    shares, position_value, loss_at_stop, gain_at_target, rr = pos
                else:
                    shares, position_value, loss_at_stop, gain_at_target, rr = 0, 0, 0, 0, 0

                rows.append({
                    "Name": name,
                    "Ticker": ticker,
                    "Status": status,
                    "Score": score,
                    "Kurs": round(close, 2),
                    "Stop": round(stop, 2),
                    "Ziel": round(target, 2),
                    "Stückzahl": int(shares),
                    "Einsatz ca.": round(position_value, 2),
                    "Risiko €": round(loss_at_stop, 2),
                    "Chance €": round(gain_at_target, 2),
                    "CRV": round(rr, 2),
                    "Gründe": " | ".join(reasons),
                    "Blocker": " | ".join(blocks),
                    "NewsRisiko": news_risk
                })
                news_blocks[ticker] = news_df
            except Exception as e:
                rows.append({"Name": name, "Ticker": ticker, "Status": f"Fehler: {e}", "Score": 0})

        result = pd.DataFrame(rows).sort_values(["Status", "Score"], ascending=[False, False])
        st.dataframe(result, use_container_width=True)

        ok = result[result["Status"].eq("OK prüfen")].head(int(max_trades))
        total_risk = ok["Risiko €"].sum() if not ok.empty else 0
        total_chance = ok["Chance €"].sum() if not ok.empty else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("Vorgeschlagene Trades", len(ok))
        c2.metric("Max. Risiko der Auswahl", money(total_risk))
        c3.metric("Max. Chance der Auswahl", money(total_chance))

        if total_risk > daily_stop:
            st.error("Auswahl überschreitet Tagesverlust-Limit. Reduziere Risiko pro Trade oder Anzahl Trades.")
        elif len(ok) == 0:
            st.info("Heute kein sauberer Trade nach deinen Regeln.")
        else:
            st.success("Diese Auswahl bleibt innerhalb deines Tagesrisikos. Trotzdem nur manuell prüfen und ausführen.")

        st.subheader("News zu ausgewählten Kandidaten")
        for _, row in ok.iterrows():
            ticker = row["Ticker"]
            st.markdown(f"### {row['Name']} ({ticker})")
            nd = news_blocks.get(ticker, pd.DataFrame())
            if nd.empty:
                st.write("Keine News gefunden.")
            else:
                st.dataframe(nd[["Titel", "Datum", "Risikowörter", "Link"]], use_container_width=True)

    else:
        st.info("Klicke links auf „Tagescheck starten“.")

with tab2:
    st.subheader("Manueller Positionsrechner")
    col1, col2, col3 = st.columns(3)
    entry = col1.number_input("Einstieg", min_value=0.0001, value=100.0)
    stop = col2.number_input("Stop-Loss", min_value=0.0001, value=97.0)
    target = col3.number_input("Take-Profit", min_value=0.0001, value=106.0)

    pos = calc_position(capital, max_position_pct, risk_per_trade, entry, stop, target)
    if pos:
        shares, position_value, loss_at_stop, gain_at_target, rr = pos
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Stückzahl", int(shares))
        c2.metric("Einsatz", money(position_value))
        c3.metric("Verlust am Stop", money(loss_at_stop))
        c4.metric("Chance am Ziel", money(gain_at_target))
        st.metric("Chance/Risiko-Verhältnis", f"{rr:.2f}")
        if rr < 1.5:
            st.error("Block: CRV unter 1,5.")
        if loss_at_stop > risk_per_trade:
            st.error("Block: Risiko pro Trade überschritten.")
    else:
        st.error("Ungültige Werte.")

with tab3:
    st.subheader("Trading Journal")
    with st.form("journal_form"):
        j_ticker = st.text_input("Ticker")
        j_direction = st.selectbox("Richtung", ["Long", "Short", "Kein Trade"])
        j_entry = st.number_input("Einstieg Journal", min_value=0.0, value=0.0)
        j_stop = st.number_input("Stop Journal", min_value=0.0, value=0.0)
        j_target = st.number_input("Ziel Journal", min_value=0.0, value=0.0)
        j_shares = st.number_input("Stückzahl Journal", min_value=0, value=0, step=1)
        j_setup = st.text_input("Setup")
        j_status = st.selectbox("Status", ["geplant", "ausgeführt", "gewonnen", "verloren", "abgebrochen"])
        j_note = st.text_area("Notiz")
        submitted = st.form_submit_button("Journal-Eintrag speichern")
        if submitted:
            risk = abs(j_entry - j_stop) * j_shares if j_entry and j_stop else 0
            chance = abs(j_target - j_entry) * j_shares if j_target and j_entry else 0
            save_journal({
                "Datum": datetime.now().isoformat(timespec="seconds"),
                "Ticker": j_ticker,
                "Richtung": j_direction,
                "Einstieg": j_entry,
                "Stop": j_stop,
                "Ziel": j_target,
                "Stückzahl": j_shares,
                "Risiko": risk,
                "Chance": chance,
                "Setup": j_setup,
                "Status": j_status,
                "Notiz": j_note
            })
            st.success("Gespeichert.")

    journal = load_journal()
    st.dataframe(journal, use_container_width=True)
    if not journal.empty:
        st.download_button("Journal als CSV herunterladen", journal.to_csv(index=False), "trading_journal.csv", "text/csv")
